import asyncio
import pyaudio
import time
import signal
from signals import Signals
import requests
import queue
from constants import *
from amazon_transcribe.client import TranscribeStreamingClient
from amazon_transcribe.model import TranscriptEvent

class AWSSTT:

    def __init__(self, signals):
        self.recorder = None
        self.mic_stream = MicrophoneStream()
        self.signals = signals
        self.API = self.API(self)
        print("🔗 Connecting to AWS Transcribe...")
        self.client = TranscribeStreamingClient(region=AWS_REGION)  # Change region if needed
        print("Connection successful!")
        self.enabled = True

    def _run_transcription_sync(self):
        """Synchronous wrapper to run the async transcription in a new thread."""
        print("Starting AWS Transcribe thread...")
        # Create a new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # Run the async method
            loop.run_until_complete(self.transcribe_microphone())
        except Exception as e:
            print(f"\n❌ Error in STT thread: {e}")
        finally:
            # Clean up the loop
            loop.close()
            print("AWS Transcribe thread finished.")

    async def transcribe_microphone(self):
        """Main transcription function"""
        print("🚀 Starting AWS Transcribe Microphone-to-Text")
        print("=" * 50)
        
        try:
            
            # Start microphone
            self.mic_stream.start_stream()
            
            # Start transcription stream
            stream = await self.client.start_stream_transcription(
                language_code="zh-TW",
                media_sample_rate_hz=16000,
                media_encoding="pcm",
                enable_partial_results_stabilization=True,
                partial_results_stability="medium"
            )
            
            print("🎯 Transcription started! Speak into your microphone...")
            print("Press Ctrl+C to stop")
            print("-" * 50)
            print("STT Ready")
            self.signals.stt_ready = True
            # Run transcription, processing output stream directly
            await asyncio.gather(
                self.write_audio_to_stream(self.mic_stream, stream),
                self.process_transcription_events(stream.output_stream)
            )
            
        except KeyboardInterrupt:
            print("\n\n🛑 Stopping transcription...")
            
        except Exception as e:
            print(f"\n❌ Error: {e}")
            print(f"Error type: {type(e).__name__}")
            
        finally:
            # Clean up
            self.mic_stream.stop_stream()


    async def write_audio_to_stream(self, mic_stream, stream):
        """Write audio chunks to the transcription stream"""
        try:
            async for chunk in mic_stream.get_audio_chunks():
                await stream.input_stream.send_audio_event(chunk)
        except Exception as e:
            print(f"Audio streaming error: {e}")
        finally:
            await stream.input_stream.end_stream()


    async def process_transcription_events(self, output_stream):
        """Processes events from the AWS Transcribe output stream."""
        
        async for event in output_stream:
            transcript_event = None
            # Check if the event is a wrapper containing TranscriptEvent
            if hasattr(event, 'TranscriptEvent') and event.TranscriptEvent is not None:
                transcript_event = event.TranscriptEvent
            # Check if the event itself is a TranscriptEvent (for robustness across SDK versions/behaviors)
            elif isinstance(event, TranscriptEvent):
                transcript_event = event

            for result in transcript_event.transcript.results:
                for alt in result.alternatives:
                    transcript = alt.transcript
                    if result.is_partial:
                        # Show partial results (real-time)
                        if not self.signals.human_speaking:
                            self.signals.human_speaking = True
                        print(f"\r💭 Partial: {transcript}", end="", flush=True)
                    else:
                        # Show complete results
                        if transcript.strip():
                            print(f"\n✅ Final: {transcript}")
                            # send message to PC here
                            payload = {
                                'text': transcript 
                            }
                            response = requests.post(SERVER_URL, data=payload, timeout=10)
                            
                            if 200 <= response.status_code < 300:
                                print(f"Success! Status: {response.status_code}, Response: {response.text[:100]}...")
                            else:
                                print(f"Error! Status: {response.status_code}, Response: {response.text[:100]}...")

                            self.signals.history.append({"role": "user", "content": transcript})
                            self.signals.last_message_time = time.time()
                            if not self.signals.AI_speaking:
                                self.signals.new_message = True
                            self.signals.human_speaking = False
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
    
    def __init__(self, rate=16000, chunk=1024):
        self.rate = rate
        self.chunk = chunk
        self.audio_queue = queue.Queue()  # Use regular queue instead of asyncio.Queue
        self.audio_stream = None
        self.pyaudio_instance = None
        self.is_recording = False
        
    def start_stream(self):
        """Start the microphone stream"""
        self.pyaudio_instance = pyaudio.PyAudio()
        
        self.audio_stream = self.pyaudio_instance.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self.rate,
            input=True,
            frames_per_buffer=self.chunk,
            stream_callback=self._audio_callback
        )
        
        self.is_recording = True
        self.audio_stream.start_stream()
        print("🎤 Microphone started. Start speaking...")
        
    def stop_stream(self):
        """Stop the microphone stream"""
        self.is_recording = False
        if self.audio_stream:
            self.audio_stream.stop_stream()
            self.audio_stream.close()
        if self.pyaudio_instance:
            self.pyaudio_instance.terminate()
        print("🛑 Microphone stopped.")
        
    def _audio_callback(self, in_data, frame_count, time_info, status):
        """Callback function for PyAudio"""
        if self.is_recording:
            # Put audio data into the queue
            try:
                self.audio_queue.put_nowait(in_data)
            except queue.Full:
                pass  # Skip if queue is full
        return (in_data, pyaudio.paContinue)
    
    async def get_audio_chunks(self):
        """Async generator that yields audio chunks"""
        while self.is_recording:
            try:
                # Get audio data from queue with timeout
                chunk = self.audio_queue.get(timeout=0.1)
                yield chunk
            except queue.Empty:
                await asyncio.sleep(0.01)  # Small delay to prevent busy waiting
                continue
    
    

def main():
    """Main entry point"""
    try:
        def signal_handler(sig, frame):
            print('Received CTRL + C, attempting to gracefully exit. Close all dashboard windows to speed up shutdown.')
            signals.terminate = True
            stt.API.shutdown()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # CORE FILES

        # Singleton object that every module will be able to read/write to
        signals = Signals()
        stt = AWSSTT(signals)
        asyncio.run(stt.transcribe_microphone())
        
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
        
    except Exception as e:
        print(f"❌ Fatal error: {e}")


if __name__ == "__main__":
    main()