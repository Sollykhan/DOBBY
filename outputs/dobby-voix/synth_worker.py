"""One local CPU synthesis request; no files or request text are logged."""
import io
import json
import sys
import wave
from pathlib import Path
from piper import PiperVoice

ROOT = Path(__file__).resolve().parent
MODELS = {'fr': 'fr_FR-tom-medium.onnx', 'en': 'en_GB-alan-medium.onnx'}

def main():
    request = json.loads(sys.stdin.buffer.read(16001))
    if set(request) != {'text', 'language'} or request['language'] not in MODELS or not isinstance(request['text'], str) or not 1 <= len(request['text']) <= 2000:
        raise ValueError('invalid_request')
    model = ROOT / 'models' / MODELS[request['language']]
    voice = PiperVoice.load(model, use_cuda=False)
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as output:
        voice.synthesize_wav(request['text'], output)
    data = buffer.getvalue()
    if len(data) > 3 * 1024 * 1024:
        raise ValueError('audio_too_large')
    sys.stdout.buffer.write(data)

if __name__ == '__main__':
    main()
