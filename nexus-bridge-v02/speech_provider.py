"""Bounded optional local Piper adapter; no request text or audio stored."""
import json
import os
from pathlib import Path
import subprocess
import threading
from speech_text import normalize_french

ROOT = Path(__file__).resolve().parent.parent / 'outputs' / 'dobby-voix'
PYTHON = ROOT / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
WORKER = ROOT / 'synth_worker.py'
MAX_AUDIO = 3 * 1024 * 1024
_lock = threading.BoundedSemaphore(1)

class SpeechUnavailable(Exception):
    pass

def synthesize(text, language='fr'):
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 500 or language not in ('fr', 'en'):
        raise ValueError('invalid_speech_request')
    if not PYTHON.is_file() or not WORKER.is_file() or not _lock.acquire(blocking=False):
        raise SpeechUnavailable('speech_unavailable')
    try:
        env = {key: os.environ[key] for key in ('SystemRoot', 'WINDIR', 'TEMP', 'TMP', 'PATH') if key in os.environ}
        spoken_text = normalize_french(text) if language == 'fr' else text
        if len(spoken_text) > 2000:
            raise ValueError('invalid_speech_request')
        request = json.dumps({'text': spoken_text, 'language': language}, ensure_ascii=True).encode('utf-8')
        result = subprocess.run([str(PYTHON), str(WORKER)], input=request, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=30, env=env, check=True, shell=False,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if len(result.stdout) > MAX_AUDIO or not result.stdout.startswith(b'RIFF') or result.stdout[8:12] != b'WAVE':
            raise SpeechUnavailable('invalid_audio')
        return result.stdout
    except (OSError, subprocess.SubprocessError):
        raise SpeechUnavailable('speech_unavailable') from None
    finally:
        _lock.release()
