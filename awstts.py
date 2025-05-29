import time
import queue
import threading
import asyncio 
import pyaudio
import boto3
from boto3.exceptions import S3UploadFailedError
from botocore.exceptions import ClientError 

# 確保這些常量在你的 constants.py 文件中定義
from constants import * 

VOICE_REFERENCE = "Joanna" 

class TTS:
    def __init__(self, signals):
        self.signals = signals
        self.API = self.API(self)
        self.enabled = True

        self.polly_client = boto3.client('polly', region_name=AWS_REGION)
        self.voice_id = VOICE_REFERENCE
        self.engine = 'neural' 
        self.output_format = 'pcm'  
        self.sample_rate = '16000' 

        self.pyaudio_instance = pyaudio.PyAudio()
        self.audio_stream = None 

        self.text_queue = queue.Queue() 
        self.audio_data_queue = queue.Queue() 

        # 標誌用於控制線程是否應該繼續運行
        self.synthesis_run_flag = threading.Event()
        self.playback_run_flag = threading.Event()

        self.synthesis_thread = None
        self.playback_thread = None

        self.signals.tts_ready = True
        print("✅ AWS Polly TTS initialized.")

    def _synthesis_worker(self):
        """獨立線程：負責從 text_queue 讀取文本，調用 Polly 進行合成，將音頻放入 audio_data_queue"""
        print("TTS Synthesis worker started.")
        try:
            # 設置初始 run_flag 為 True，以便進入循環，但後續會檢查
            self.synthesis_run_flag.set() 
            
            while self.synthesis_run_flag.is_set(): # 只有當 run_flag 為 True 時才循環
                try:
                    # 阻塞式獲取，如果收到 None 哨兵則退出
                    # timeout 設置為 0.5 秒，以允許在線程應該停止時能快速退出
                    message = self.text_queue.get(timeout=0.5) 
                    if message is None: # 收到停止信號
                        print("Synthesis worker received stop sentinel (None). Exiting loop.")
                        break # 退出 while 循環

                    if not message.strip():
                        continue

                    response = self.polly_client.synthesize_speech(
                        OutputFormat=self.output_format,
                        Text=message,
                        VoiceId=self.voice_id,
                        Engine=self.engine,
                        SampleRate=self.sample_rate
                    )
                    
                    if "AudioStream" in response:
                        audio_stream = response["AudioStream"]
                        
                        chunk_size = 1024 * 4 
                        while True:
                            chunk = audio_stream.read(chunk_size)
                            if not chunk:
                                break
                            self.audio_data_queue.put(chunk)
                        audio_stream.close() 
                    else:
                        print(f"⚠️ Polly did not return an audio stream for message: {message[:50]}...")
                except queue.Empty:
                    # 隊列為空，短暫休眠，然後再次檢查 run_flag 狀態
                    time.sleep(0.01)
                except ClientError as e: 
                    print(f"❌ Polly Client Error during synthesis: {e}")
                except Exception as e:
                    print(f"❌ Error in synthesis worker: {e}")
        finally:
            # 合成結束時，放入一個 None 作為播放結束的信號
            # 這很重要，因為播放器需要知道何時停止
            self.audio_data_queue.put(None) # 確保在合成線程退出前發送停止信號
            self.synthesis_thread = None # 重置線程對象，允許下次重新啟動
            print("TTS Synthesis worker finished.")


    def _playback_worker(self):
        """獨立線程：負責從 audio_data_queue 讀取音頻，使用 PyAudio 進行播放"""
        print("TTS Playback worker started.")
        try:
            self.audio_stream = self.pyaudio_instance.open(
                format=self.pyaudio_instance.get_format_from_width(2), 
                channels=1, 
                rate=int(self.sample_rate),
                output=True,
                output_device_index=OUTPUT_DEVICE_INDEX
            )
            
            self.signals.AI_speaking = True 
            self.signals.last_message_time = time.time() 
            
            # 設置初始 run_flag 為 True
            self.playback_run_flag.set() 

            while self.playback_run_flag.is_set(): # 只有當 run_flag 為 True 時才循環
                try:
                    # 阻塞式獲取，如果收到 None 哨兵則退出
                    # timeout 設置為 0.5 秒，以允許在線程應該停止時能快速退出
                    audio_chunk = self.audio_data_queue.get(timeout=0.5)
                    if audio_chunk is None: # 收到停止信號
                        print("Playback worker received stop sentinel (None). Exiting loop.")
                        break # 退出 while 循環
                    
                    if self.audio_stream and self.audio_stream.is_active():
                        self.audio_stream.write(audio_chunk)
                    else:
                        print("PyAudio stream is not active, stopping playback worker.")
                        break # Stream not active, stop
                except queue.Empty:
                    # 隊列為空，短暫休眠，然後再次檢查 run_flag 狀態
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
            self.playback_thread = None # 重置線程對象，允許下次重新啟動
            print("TTS Playback worker finished.")


    def play(self, message):
        # 如果 TTS 被禁用，或者消息為空，直接返回
        if not self.enabled or not message.strip():
            if not self.enabled:
                print("TTS is disabled. Not playing.")
            return

        self.signals.sio_queue.put(("current_message", message))
        
        # 啟動線程（如果尚未啟動），並設置運行標誌
        # 注意：這裡的 run_flag 必須在線程啟動前設置為 True
        # 但在 worker 內部也做了設置，這是為了確保線程啟動後它的狀態是正確的
        if self.synthesis_thread is None or not self.synthesis_thread.is_alive():
            # self.synthesis_run_flag.set() # 這裡不需要，因為 worker 內部會設置
            self.synthesis_thread = threading.Thread(target=self._synthesis_worker, daemon=True)
            self.synthesis_thread.start()
            print("Synthesis thread started.") # 調試信息

        if self.playback_thread is None or not self.playback_thread.is_alive():
            # self.playback_run_flag.set() # 這裡不需要，因為 worker 內部會設置
            self.playback_thread = threading.Thread(target=self._playback_worker, daemon=True)
            self.playback_thread.start()
            print("Playback thread started.") # 調試信息

        # 將文本放入隊列，確保在線程啟動後放入
        self.text_queue.put(message)
        print(f"Queued message: {message[:30]}...") # 打印隊列消息，方便調試


    def stop(self):
        """立即停止所有語音合成和播放，並清除隊列"""
        print("TTS stop called.")
        
        # 1. 設置運行標誌為 False，通知線程停止新操作
        self.synthesis_run_flag.clear()
        self.playback_run_flag.clear()
        print("Run flags cleared.")

        # 2. 向 text_queue 放入哨兵 (None)，指示合成線程結束
        # 只有當合成線程存在且仍在運行時才放入哨兵
        # 這個判斷是為了避免向一個已經結束的線程的隊列發送哨兵
        if self.synthesis_thread and self.synthesis_thread.is_alive():
            self.text_queue.put(None) 
            print("Sent stop sentinel to synthesis queue.")
        else:
            print("Synthesis thread not active or already terminated, no sentinel sent to text queue.")
        
        # 3. 等待合成線程結束
        # 檢查 self.synthesis_thread 是否為 None 且是否仍然存活
        print(f"DEBUG: Checking synthesis_thread (is_alive={self.synthesis_thread.is_alive() if self.synthesis_thread else 'None'})")
        # 關鍵：在調用 .is_alive() 之前，先確保 self.synthesis_thread 不是 None
        if self.synthesis_thread is not None: # <-- 先檢查是否為 None
            if self.synthesis_thread.is_alive(): # <-- 再檢查是否存活
                print("Joining synthesis thread...")
                # 增加 timeout 以確保有足夠時間處理哨兵並退出
                self.synthesis_thread.join(timeout=5) 
                if self.synthesis_thread.is_alive():
                    print("⚠️ Synthesis thread did not terminate within timeout.")
                else:
                    print("Synthesis thread successfully joined.")
            else:
                print("Synthesis thread was not alive (already terminated) before join attempt.")
        else:
            print("Synthesis thread object was None before join attempt.")
        
        # 4. 等待播放線程結束
        # 同樣，檢查 self.playback_thread 是否為 None 且是否仍然存活
        print(f"DEBUG: Checking playback_thread (is_alive={self.playback_thread.is_alive() if self.playback_thread else 'None'})")
        if self.playback_thread is not None: # <-- 先檢查是否為 None
            if self.playback_thread.is_alive(): # <-- 再檢查是否存活
                print("Joining playback thread...")
                # 增加 timeout
                self.playback_thread.join(timeout=5)
                if self.playback_thread.is_alive():
                    print("⚠️ Playback thread did not terminate within timeout.")
                else:
                    print("Playback thread successfully joined.")
            else:
                print("Playback thread was not alive (already terminated) before join attempt.")
        else:
            print("Playback thread object was None before join attempt.")
            
        # 5. 清除所有隊列中可能殘留的項目
        # 雖然線程應已處理哨兵，但為了安全仍清空
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

# 為了測試，這裡提供一個簡單的 MockSignals 類
class MockSignals:
    def __init__(self):
        self.tts_ready = False
        self.AI_speaking = False
        self.last_message_time = None
        self.sio_queue = queue.Queue() 

# 主執行部分 (用於測試)
if __name__ == "__main__":
    try:
        boto3.client('sts').get_caller_identity()
        print("✅ AWS credentials found and valid.")
    except Exception as e:
        print(f"❌ AWS credentials invalid or not found: {e}")
        print("Please configure AWS credentials using 'aws configure' or environment variables.")
        exit(1)

    signals = MockSignals()
    tts_instance = TTS(signals)

    print("TTS system ready, testing...")
    print(f"TTS ready: {signals.tts_ready}")

    time.sleep(1)

    print("\n--- Test 1: Basic Playback ---")
    tts_instance.play("Hello, this is a voice test from Amazon Polly.")
    time.sleep(3) 

    tts_instance.play("I hope it works well and you can hear this.")
    time.sleep(2)

    tts_instance.play("This is a longer text to test continuous playback. The longer the text, the longer the synthesis, but playback should be continuous.")
    time.sleep(5)

    print("\n--- Test 2: Stop Function ---")
    tts_instance.play("This sentence should be interrupted.") 
    time.sleep(0.5) 
    tts_instance.stop() 
    print("TTS stopped.")
    time.sleep(2) 

    print("\n--- Test 3: Restart After Stop ---")
    tts_instance.play("Restarting playback, this should be a new sentence.")
    time.sleep(4)

    print("\n--- Test 4: Disable TTS ---")
    tts_instance.API.set_TTS_status(False)
    tts_instance.play("This sentence should not be played.")
    time.sleep(2)
    print(f"TTS enabled status: {tts_instance.API.get_TTS_status()}")

    print("\n--- Test 5: Re-enable TTS ---")
    tts_instance.API.set_TTS_status(True)
    tts_instance.play("Now TTS should be enabled again, and this sentence will be played.")
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