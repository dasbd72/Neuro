import time
from RealtimeTTS import TextToAudioStream, CoquiEngine
from constants import *
import queue
import threading
import pyaudio
import google.cloud.texttospeech as googletts

class LOCALTTS:
    def __init__(self, signals):
        self.stream = None
        self.signals = signals
        self.API = self.API(self)
        self.enabled = True

        engine = CoquiEngine(
            model_name=TTS_MODEL_NAME,
            use_deepspeed=True,
            voice="./voices/" + VOICE_REFERENCE,
            speed=1.1,
            language=LANGUAGE,
        )
        tts_config = {
            'on_audio_stream_start': self.audio_started,
            'on_audio_stream_stop': self.audio_ended,
            'output_device_index': OUTPUT_DEVICE_INDEX,
            'tokenizer': TTS_REALTIME_TOKENIZER,
            'language': LANGUAGE,
        }
        self.stream = TextToAudioStream(engine, **tts_config)
        self.signals.tts_ready = True

    def play(self, message):
        if not self.enabled:
            return

        # If the message is only whitespace, don't attempt to play it
        if not message.strip():
            return

        self.signals.sio_queue.put(("current_message", message))
        self.stream.feed(message)
        self.stream.play_async(
            tokenizer=TTS_REALTIME_TOKENIZER,
            language=LANGUAGE,
        )

    def stop(self):
        self.stream.stop()
        self.signals.AI_speaking = False

    def audio_started(self):
        self.signals.AI_speaking = True

    def audio_ended(self):
        self.signals.last_message_time = time.time()
        self.signals.AI_speaking = False

    class API:
        def __init__(self, outer):
            self.outer = outer

        def set_TTS_status(self, status):
            self.outer.enabled = status
            if not status:
                self.outer.stop()
            self.outer.signals.sio_queue.put(('TTS_status', status))

        def get_TTS_status(self):
            return self.outer.enabled

        def abort_current(self):
            self.outer.stop()

class SpeakerStream:
    """Speaker audio stream using PyAudio"""
    def __init__(self, device_index=0, on_audio_start=None, on_audio_end=None):
        self.device_index = device_index
        self.on_audio_start = on_audio_start
        self.on_audio_end = on_audio_end
        self.audio_queue = queue.Queue()
        self.pyaudio_instance = None
        self.audio_stream = None
        self.is_streaming = False
        self._streaming_thread = None

    def start_stream(self):
        """Start the audio stream for playback."""
        self.pyaudio_instance = pyaudio.PyAudio()
        self.audio_stream = self.pyaudio_instance.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=24000,
            output=True,
            output_device_index=self.device_index,
            frames_per_buffer=1024,
        )
        self.is_streaming = True
        self._streaming_thread = threading.Thread(target=self._play_audio)
        self._streaming_thread.daemon = True
        self._streaming_thread.start()

    def _play_audio(self):
        """Continuously play audio from the queue."""
        while self.is_streaming:
            try:
                audio_content = self.audio_queue.get(timeout=1) # Get audio data with a timeout
                if self.on_audio_start:
                    self.on_audio_start()
                self.audio_stream.write(audio_content)
                self.audio_queue.task_done()
                if self.on_audio_end:
                    self.on_audio_end()
            except queue.Empty:
                # No audio in queue, continue checking
                time.sleep(0.1) # Small delay to prevent busy-waiting
            except Exception as e:
                print(f"Error during audio playback: {e}")
                self.stop_stream() # Stop playback on error

    def stop_stream(self):
        """Stop the audio stream and clean up resources."""
        self.is_streaming = False
        if self._streaming_thread and self._streaming_thread.is_alive():
            self._streaming_thread.join(timeout=2) # Wait for playback thread to finish
            if self._streaming_thread.is_alive():
                print("Warning: Playback thread did not terminate cleanly.")
        if self.audio_stream:
            self.audio_stream.stop_stream()
            self.audio_stream.close()
            self.audio_stream = None
        if self.pyaudio_instance:
            self.pyaudio_instance.terminate()

    def put_audio(self, audio_content):
        """Put audio content into the queue for playback."""
        self.audio_queue.put(audio_content)

class GOOGLETTS(LOCALTTS):
    def __init__(self, signals):
        self.signals = signals
        self.API = self.API(self)
        self.enabled = True

        # Initialize Google TTS client
        self.client = googletts.TextToSpeechClient()
        self.speaker_stream = SpeakerStream(device_index=OUTPUT_DEVICE_INDEX, on_audio_start=self.audio_started, on_audio_end=self.audio_ended)
        self.speaker_stream.start_stream()
        self.signals.tts_ready = True

    def play(self, message):
        if not self.enabled:
            return

        # If the message is only whitespace, don't attempt to play it
        if not message.strip():
            return
        
        self.signals.sio_queue.put(("current_message", message))
        self.signals.AI_speaking = True
        self._synthesize_and_play(message)

    def _synthesize_and_play(self, text):
        language_code = "-".join(TTS_GOOGLE_VOICE_NAME.split("-")[:2])
        text_input = googletts.SynthesisInput(text=text)
        voice_params = googletts.VoiceSelectionParams(
            language_code=language_code,
            name=TTS_GOOGLE_VOICE_NAME,  # Ensure this is set in constants.py
        )
        audio_config = googletts.AudioConfig(
            audio_encoding=googletts.AudioEncoding.LINEAR16,
            speaking_rate=1.4,  # Adjust as needed
        )
        response = self.client.synthesize_speech(
            input=text_input,
            voice=voice_params,
            audio_config=audio_config,
        )
        audio_content = response.audio_content
        self.speaker_stream.put_audio(audio_content)

    def stop(self):
        self.signals.AI_speaking = False
        self.speaker_stream.stop_stream()

if TTS_SERVER == "local":
    TTS = LOCALTTS
elif TTS_SERVER == "google":
    TTS = GOOGLETTS
else:
    raise ValueError(f"Invalid TTS_SERVER value: {TTS_SERVER}.")
