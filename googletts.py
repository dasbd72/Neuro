import time
import queue
import threading
import pyaudio
import os 

from google.cloud import texttospeech

# 假設這些常量在你的 constants.py 文件中定義
from constants import * 

# Google Cloud TTS 相關配置
# 選擇一個英文語音。繼續使用 Neural2-C，或者您也可以嘗試 Neural2-E
GCP_VOICE_NAME = "en-US-Neural2-C" 
GCP_LANGUAGE_CODE = "en-US" 
GCP_SSML_GENDER = texttospeech.SsmlVoiceGender.FEMALE 

class TTS:
    def __init__(self, signals):
        self.signals = signals
        self.API = self.API(self)
        self.enabled = True

        self.tts_client = texttospeech.TextToSpeechClient()

        self.voice = texttospeech.VoiceSelectionParams(
            language_code=GCP_LANGUAGE_CODE,
            name=GCP_VOICE_NAME,
            ssml_gender=GCP_SSML_GENDER,
        )

        self.audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16, 
            sample_rate_hertz=16000, 
            speaking_rate=0.95, # 保持語速為正常，或略微加快 (例如 1.05-1.15)
            pitch=2.0 # <--- 將全局音高降低到一個更溫和的值。精細調整交給 SSML。
        )
        
        self.pyaudio_instance = pyaudio.PyAudio()
        self.audio_stream = None 

        self.text_queue = queue.Queue() # 存放待合成的文本 (可以是普通文本或 SSML)
        self.audio_data_queue = queue.Queue() 

        self.synthesis_run_flag = threading.Event()
        self.playback_run_flag = threading.Event()

        self.synthesis_thread = None
        self.playback_thread = None

        self.signals.tts_ready = True
        print("✅ Google Cloud TTS initialized.")

    def _synthesis_worker(self):
        print("TTS Synthesis worker started.")
        try:
            self.synthesis_run_flag.set() 
            
            while self.synthesis_run_flag.is_set(): 
                try:
                    # message 可以是普通文本或帶有 SSML 標籤的文本
                    message = self.text_queue.get(timeout=0.5) 
                    if message is None: 
                        print("Synthesis worker received stop sentinel (None). Exiting loop.")
                        break 

                    if not message.strip():
                        continue

                    # 判斷是否是 SSML 格式
                    if message.strip().startswith("<speak>"):
                        synthesis_input = texttospeech.SynthesisInput(ssml=message)
                    else:
                        synthesis_input = texttospeech.SynthesisInput(text=message)
                    
                    response = self.tts_client.synthesize_speech(
                        input=synthesis_input, 
                        voice=self.voice, 
                        audio_config=self.audio_config
                    )
                    
                    if response.audio_content:
                        self.audio_data_queue.put(response.audio_content)
                    else:
                        print(f"⚠️ Google Cloud TTS did not return audio for message: {message[:50]}...")
                except queue.Empty:
                    time.sleep(0.01)
                except Exception as e: 
                    print(f"❌ Google Cloud TTS API Error during synthesis: {e}")
        finally:
            self.audio_data_queue.put(None) 
            self.synthesis_thread = None 
            print("TTS Synthesis worker finished.")


    def _playback_worker(self):
        print("TTS Playback worker started.")
        try:
            self.audio_stream = self.pyaudio_instance.open(
                format=self.pyaudio_instance.get_format_from_width(2), 
                channels=1, 
                rate=self.audio_config.sample_rate_hertz,
                output=True,
                output_device_index=OUTPUT_DEVICE_INDEX
            )
            
            self.signals.AI_speaking = True 
            self.signals.last_message_time = time.time() 
            
            self.playback_run_flag.set() 

            while self.playback_run_flag.is_set(): 
                try:
                    audio_chunk = self.audio_data_queue.get(timeout=0.5)
                    if audio_chunk is None: 
                        print("Playback worker received stop sentinel (None). Exiting loop.")
                        break 
                    
                    if self.audio_stream and self.audio_stream.is_active():
                        self.audio_stream.write(audio_chunk) 
                    else:
                        print("PyAudio stream is not active, stopping playback worker.")
                        break 
                except queue.Empty:
                    time.sleep(0.01)
                except Exception as e:
                    print(f"❌ Error in playback worker: {e}")
                    break 

        except Exception as e:
            print(f"❌ Error initializing PyAudio stream or in playback loop: {e}")
        finally:
            if self.audio_stream:
                if self.audio_stream.is_active():
                    self.audio_stream.stop_stream()
                self.audio_stream.close()
                self.audio_stream = None 
            
            self.signals.AI_speaking = False 
            self.playback_thread = None 
            print("TTS Playback worker finished.")


    def play(self, message):
        if not self.enabled or not message.strip():
            if not self.enabled:
                print("TTS is disabled. Not playing.")
            return

        self.signals.sio_queue.put(("current_message", message))
        
        if self.synthesis_thread is None or not self.synthesis_thread.is_alive():
            self.synthesis_run_flag.set() 
            self.synthesis_thread = threading.Thread(target=self._synthesis_worker, daemon=True)
            self.synthesis_thread.start()
            print("Synthesis thread started.") 

        if self.playback_thread is None or not self.playback_thread.is_alive():
            self.playback_run_flag.set() 
            self.playback_thread = threading.Thread(target=self._playback_worker, daemon=True)
            self.playback_thread.start()
            print("Playback thread started.") 

        self.text_queue.put(message)
        print(f"Queued message: {message[:30]}...") 


    def stop(self):
        print("TTS stop called.")
        
        self.synthesis_run_flag.clear()
        self.playback_run_flag.clear()
        print("Run flags cleared.")

        current_synthesis_thread = self.synthesis_thread
        current_playback_thread = self.playback_thread

        if current_synthesis_thread and current_synthesis_thread.is_alive():
            self.text_queue.put(None) 
            print("Sent stop sentinel to synthesis queue.")
        else:
            print("Synthesis thread not active or already terminated, no sentinel sent to text queue.")
        
        print(f"DEBUG: Checking synthesis_thread (is_alive={current_synthesis_thread.is_alive() if current_synthesis_thread else 'None'})")
        if current_synthesis_thread is not None:
            if current_synthesis_thread.is_alive():
                print("Joining synthesis thread...")
                current_synthesis_thread.join(timeout=5) 
                if current_synthesis_thread.is_alive():
                    print("⚠️ Synthesis thread did not terminate within timeout.")
                else:
                    print("Synthesis thread successfully joined.")
            else:
                print("Synthesis thread was not alive (already terminated) before join attempt.")
        else:
            print("Synthesis thread object was None before join attempt.")
        
        print(f"DEBUG: Checking playback_thread (is_alive={current_playback_thread.is_alive() if current_playback_thread else 'None'})")
        if current_playback_thread is not None:
            if current_playback_thread.is_alive():
                print("Joining playback thread...")
                current_playback_thread.join(timeout=5)
                if current_playback_thread.is_alive():
                    print("⚠️ Playback thread did not terminate within timeout.")
                else:
                    print("Playback thread successfully joined.")
            else:
                print("Playback thread was not alive (already terminated) before join attempt.")
        else:
            print("Playback thread object was None before join attempt.")
            
        while not self.text_queue.empty():
            try: self.text_queue.get_nowait()
            except queue.Empty: pass
        while not self.audio_data_queue.empty():
            try: self.audio_data_queue.get_nowait()
            except queue.Empty: pass
        
        self.signals.AI_speaking = False
        print("TTS stopped and queues cleared.")


    class API:
        def __init__(self, outer):
            self.outer = outer

        def set_TTS_status(self, status):
            self.outer.enabled = status
            if not status:
                self.outer.stop() 
            self.outer.signals.sio_queue.put(('TTS_status', status))
            print(f"TTS status set to: {status}")

        def get_TTS_status(self):
            return self.outer.enabled

        def abort_current(self):
            print("TTS API: abort_current called.")
            self.outer.stop() 

class MockSignals:
    def __init__(self):
        self.tts_ready = False
        self.AI_speaking = False
        self.last_message_time = None
        self.sio_queue = queue.Queue() 

if __name__ == "__main__":
    if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        print("❌ GOOGLE_APPLICATION_CREDENTIALS environment variable not set.")
        print("Please set it to the path of your Google Cloud service account JSON key file.")
        print("Example: export GOOGLE_APPLICATION_CREDENTIALS=\"/path/to/your/key.json\"")
        exit(1)
    else:
        print("✅ GOOGLE_APPLICATION_CREDENTIALS environment variable found.")

    signals = MockSignals()
    tts_instance = TTS(signals)

    print("TTS system ready, testing...")
    print(f"TTS ready: {signals.tts_ready}")

    time.sleep(1)

    print("\n--- Test 1: Basic Playback with SSML ---")
    # 使用 SSML 來增加語音的表情和變化
    # <speak> 是根元素
    # <prosody> 用於調整語速和音高
    # <emphasis> 用於強調特定詞語
    # <break> 用於增加停頓
    ssml_text1 = """
    <speak>
<prosody rate="fast" pitch="medium">
Gotcha, I will stick to a medium pitch<break time="0.2s"/> from now on, sweetie!
</prosody>
</speak>
    """
    tts_instance.play(ssml_text1)
    time.sleep(5) 

    ssml_text2 = """
    <speak>
<prosody rate="medium" pitch="high">
Sorry, chat<break time="0.2s"/>, but long stories aren't really my thing<break time="0.2s"/>-- I specialize in quick bursts of <emphasis level="strong">fabulous</emphasis> facts<break time="0.2s"/>!
</prosody>
</speak>
    """
    tts_instance.play(ssml_text2)
    time.sleep(5)

    ssml_text3 = """
    <speak>
      <prosody rate="slow" pitch="medium">
        Hmm, <break time="0.5s"/> sometimes, <emphasis level="strong">thinking</emphasis> is a bit hard.
        But I'll always try my best!
      </prosody>
    </speak>
    """
    tts_instance.play(ssml_text3)
    time.sleep(7)

    print("\n--- Test 2: Stop Function with SSML ---")
    ssml_text_interrupt = """
    <speak>
      <prosody rate="fast" pitch="high">
        This sentence should be <emphasis level="strong">interrupted</emphasis> very, very quickly.
      </prosody>
    </speak>
    """
    tts_instance.play(ssml_text_interrupt) 
    time.sleep(0.5) 
    tts_instance.stop() 
    print("TTS stopped.")
    time.sleep(2) 

    print("\n--- Test 3: Restart After Stop with SSML ---")
    ssml_text_restart = """
    <speak>
      <prosody rate="medium" pitch="high">
        Yay! Restarting playback! <break time="0.2s"/> This should be a <emphasis level="strong">brand new</emphasis> sentence!
      </prosody>
    </speak>
    """
    tts_instance.play(ssml_text_restart)
    time.sleep(6)

    print("\n--- Test 4: Disable TTS ---")
    tts_instance.API.set_TTS_status(False)
    tts_instance.play("This sentence should not be played. SSML will not help here.")
    time.sleep(2)
    print(f"TTS enabled status: {tts_instance.API.get_TTS_status()}")

    print("\n--- Test 5: Re-enable TTS ---")
    tts_instance.API.set_TTS_status(True)
    ssml_text_reenable = """
    <speak>
      <prosody rate="medium" pitch="x-high">
        Alright! <break time="0.1s"/> TTS is enabled again! Let's talk more!
      </prosody>
    </speak>
    """
    tts_instance.play(ssml_text_reenable)
    time.sleep(4)

    print("\nFinished TTS testing.")
    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nExiting main program...")
        tts_instance.stop()
        if tts_instance.pyaudio_instance:
            tts_instance.pyaudio_instance.terminate()