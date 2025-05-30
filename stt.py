import logging
import time
from RealtimeSTT import AudioToTextRecorder
from constants import *
import queue
import asyncio
import pyaudio
from amazon_transcribe.client import TranscribeStreamingClient
from amazon_transcribe.model import TranscriptEvent, StartStreamTranscriptionEventStream, TranscriptResultStream


class LOCALSTT:
    def __init__(self, signals):
        self.recorder = None
        self.signals = signals
        self.API = self.API(self)
        self.enabled = True

    def process_text(self, text):
        if not self.enabled:
            return

        print("STT OUTPUT: " + text)
        if WAKE_PROMPTS:
            is_waking = False
            if LANGUAGE == "en":
                # Check if the text start with wake prompts
                for wake_prompt in WAKE_PROMPTS:
                    if text.startswith(wake_prompt):
                        is_waking = True
                        text = text.lstrip(wake_prompt)
                        break
            elif LANGUAGE == "zh":
                import pypinyin
                text_seq = pypinyin.lazy_pinyin(text)
                wake_seqs = [pypinyin.lazy_pinyin(word) for word in WAKE_PROMPTS]
                # Check if the text start with wake prompts
                for wake_seq in wake_seqs:
                    if text_seq[:len(wake_seq)] == wake_seq:
                        is_waking = True
                        text = text[len(wake_seq):]
                        break
            if not is_waking:
                # If the text does not contain the wake prompt, ignore it
                print("STT: Ignoring text without wake prompt")
                return
        self.signals.history.append({"role": "user", "content": text})

        self.signals.last_message_time = time.time()
        if not self.signals.AI_speaking:
            self.signals.new_message = True

    def recording_start(self):
        self.signals.human_speaking = True

    def recording_stop(self):
        self.signals.human_speaking = False

    def feed_audio(self, data):
        self.recorder.feed_audio(data)

    def listen_loop(self):
        print("STT Starting")
        recorder_config = {
            'spinner': False,
            'language': LANGUAGE,
            'use_microphone': True,
            'input_device_index': INPUT_DEVICE_INDEX,
            'silero_sensitivity': 0.6,
            'silero_use_onnx': True,
            'post_speech_silence_duration': 0.4,
            'min_length_of_recording': 0,
            'min_gap_between_recordings': 0.2,
            'enable_realtime_transcription': True,
            'realtime_processing_pause': 0.2,
            'realtime_model_type': STT_REALTIME_MODEL_TYPE,
            'compute_type': 'auto',
            'on_recording_start': self.recording_start,
            'on_recording_stop': self.recording_stop,
            'level': logging.ERROR
        }

        with AudioToTextRecorder(**recorder_config) as recorder:
            self.recorder = recorder
            print("STT Ready")
            self.signals.stt_ready = True
            while not self.signals.terminate:
                if not self.enabled:
                    time.sleep(0.2)
                    continue
                recorder.text(self.process_text)

    class API:
        def __init__(self, outer):
            self.outer = outer

        def set_STT_status(self, status):
            self.outer.enabled = status
            self.outer.signals.sio_queue.put(('STT_status', status))

        def get_STT_status(self):
            return self.outer.enabled

        def shutdown(self):
            self.outer.recorder.stop()
            self.outer.recorder.interrupt_stop_event.set()

class MicrophoneStream:
    """Microphone audio stream using PyAudio"""
    def __init__(self, device_index=0, sample_rate=16000, chunk_size=1024):
        self.device_index = device_index
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.audio_queue = queue.Queue()  # Use regular queue instead of asyncio.Queue
        self.pyaudio_instance = None
        self.audio_stream = None
        self.is_streaming = False

    def start_stream(self):
        """Start the microphone stream"""
        self.pyaudio_instance = pyaudio.PyAudio()
        self.audio_stream = self.pyaudio_instance.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self.sample_rate,
            input=True,
            frames_per_buffer=self.chunk_size,
            input_device_index=self.device_index,
            stream_callback=self._audio_callback
        )
        self.is_streaming = True
        self.audio_stream.start_stream()

    def stop_stream(self):
        """Stop the microphone stream"""
        self.is_streaming = False
        if self.audio_stream:
            self.audio_stream.stop_stream()
            self.audio_stream.close()
        if self.pyaudio_instance:
            self.pyaudio_instance.terminate()

    def _audio_callback(self, in_data, frame_count, time_info, status):
        """Callback function for PyAudio"""
        if self.is_streaming:
            # Put audio data into the queue
            try:
                self.audio_queue.put_nowait(in_data)
            except queue.Full:
                pass  # Skip if queue is full
        return (in_data, pyaudio.paContinue)

    async def get_audio_chunks(self):
        """Async generator that yields audio chunks"""
        while self.is_streaming:
            try:
                # Get audio data from queue with timeout
                chunk = self.audio_queue.get(timeout=0.1)
                yield chunk
            except queue.Empty:
                await asyncio.sleep(0.01)  # Small delay to prevent busy waiting
                continue

class AWSSTT(LOCALSTT):
    def __init__(self, signals):
        self.recorder = None
        self.signals = signals
        self.API = self.API(self)
        self.enabled = True
        self.mic_stream = MicrophoneStream()
        self.client = TranscribeStreamingClient(region=STT_AWS_REGION)

        self.is_human_speaking = False # Simulates the human speaking state

    async def transcribe_microphone(self):        
        # Start microphone
        self.mic_stream.start_stream()

        # Start transcription stream
        stream = await self.client.start_stream_transcription(
            language_code=STT_AWS_LANGUAGE,
            media_sample_rate_hz=16000,
            media_encoding="pcm",
            enable_partial_results_stabilization=True,
            partial_results_stability="medium",
        )

        self.signals.stt_ready = True
        # Run transcription, processing output stream directly
        await asyncio.gather(
            self.write_audio_to_stream(self.mic_stream, stream),
            self.process_transcription_events(stream.output_stream)
        )

    async def write_audio_to_stream(self, mic_stream: MicrophoneStream, stream: StartStreamTranscriptionEventStream):
        """Write audio chunks to the transcription stream"""
        async for chunk in mic_stream.get_audio_chunks():
            await stream.input_stream.send_audio_event(chunk)

    async def process_transcription_events(self, output_stream: TranscriptResultStream):
        """Processes events from the AWS Transcribe output stream."""
        async for event in output_stream:
            transcript_event = None
            if isinstance(event, TranscriptEvent):
                transcript_event = event
            for result in transcript_event.transcript.results:
                for alt in result.alternatives:
                    transcript = alt.transcript
                    if result.is_partial and not self.is_human_speaking:
                        self.is_human_speaking = True
                        self.recording_start()
                    if not result.is_partial and transcript.strip():
                        self.process_text(transcript)
                        self.is_human_speaking = False
                        self.recording_stop()

    def listen_loop(self):
        print("AWSSTT Starting")
        while not self.signals.terminate:
            if not self.enabled:
                time.sleep(0.2)
                continue
            # Start the transcription loop
            asyncio.run(self.transcribe_microphone())

    class API:
        def __init__(self, outer: 'AWSSTT'):
            self.outer = outer

        def set_STT_status(self, status):
            self.outer.enabled = status
            self.outer.signals.sio_queue.put(('STT_status', status))

        def get_STT_status(self):
            return self.outer.enabled

        def shutdown(self):
            self.outer.mic_stream.stop_stream()

if STT_SERVER == "local":
    STT = LOCALSTT
elif STT_SERVER == "aws":
    STT = AWSSTT
else:
    raise ValueError(f"Invalid STT_SERVER value: {STT_SERVER}.")
