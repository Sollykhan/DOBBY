"""Responses API architect: bounded calls and strictly validated messages."""
import asyncio
import json
import os
import re
import urllib.error
import urllib.request
from decimal import Decimal

from bridge import BridgeError, validate_message
from codex_adapter import TASK_ID

ENDPOINT = 'https://api.openai.com/v1/responses'
DEFAULT_MODEL = 'gpt-6-luna'
MODELS = ('gpt-6-luna', 'gpt-6.1-terra')
MAX_CALLS = 6
MAX_OUTPUT_TOKENS = 256
MAX_REQUEST_BYTES = 12000
MAX_RESPONSE_BYTES = 32768
REQUEST_TIMEOUT = 20
RESERVATION = Decimal('0.02')
SOFTWARE_BUDGET = Decimal('0.12')


def schema_for(stage):
    properties = {'type': {'type': 'string', 'enum': ['proposal' if stage == 'plan' else 'review']},
                  'summary': {'type': 'string'}}
    if stage == 'plan':
        properties['task'] = {'type': 'string', 'enum': [TASK_ID]}
    else:
        properties['decision'] = {'type': 'string', 'enum': ['accept', 'revise']}
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


def reject_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate')
        result[key] = value
    return result


def request_api(key, payload):
    raw = json.dumps(payload, ensure_ascii=True, separators=(',', ':')).encode()
    if len(raw) > MAX_REQUEST_BYTES:
        raise BridgeError('architect_input_limit')
    request = urllib.request.Request(ENDPOINT, data=raw,
        headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, method='POST')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=REQUEST_TIMEOUT) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except (urllib.error.URLError, OSError, TimeoutError):
        raise BridgeError('architect_request_failed') from None
    if len(body) > MAX_RESPONSE_BYTES:
        raise BridgeError('architect_response_limit')
    return body


class OpenAIArchitect:
    def __init__(self, model=DEFAULT_MODEL, transport=request_api):
        if model not in MODELS:
            raise ValueError('unsupported model')
        self.model, self.transport = model, transport
        self.calls = 0
        self.reserved = Decimal('0')

    async def plan(self, task, history):
        return await self._call('plan', task, history)

    async def review(self, task, history):
        return await self._call('review', task, history)

    async def _call(self, stage, task, history):
        key = os.environ.get('OPENAI_API_KEY', '')
        if not key or not key.strip() or '\n' in key or '\r' in key:
            raise BridgeError('architect_api_key_missing')
        if self.calls >= MAX_CALLS or self.reserved + RESERVATION > SOFTWARE_BUDGET:
            raise BridgeError('architect_budget_exhausted')
        context = json.dumps({'task': task, 'history': history}, ensure_ascii=True, separators=(',', ':'))
        if key in context:
            raise BridgeError('architect_sensitive_input')
        instructions = ('You are the DOBBY architect. Only propose task analyze:nexus-test, '
            'a fixed read-only Codex analysis. Never request commands or paths. '
            'Review the sanitized Codex result and either accept or request a revision. '
            'Summaries must be concise and must never include credentials.')
        payload = {'model': self.model, 'store': False, 'max_output_tokens': MAX_OUTPUT_TOKENS,
                   'instructions': instructions, 'input': context,
                   'text': {'format': {'type': 'json_schema', 'name': 'dobby_' + stage,
                                       'strict': True, 'schema': schema_for(stage)}}}
        self.calls += 1
        self.reserved += RESERVATION
        try:
            raw = await asyncio.to_thread(self.transport, key, payload)
            if len(raw) > MAX_RESPONSE_BYTES or key.encode() in raw:
                raise BridgeError('architect_response_refused')
            response = json.loads(raw, object_pairs_hook=reject_duplicates)
            if response.get('status') != 'completed':
                raise ValueError('not completed')
            texts = [part['text'] for item in response['output'] if item.get('type') == 'message'
                     for part in item['content'] if part.get('type') == 'output_text']
            if len(texts) != 1:
                raise ValueError('unexpected output')
            value = json.loads(texts[0], object_pairs_hook=reject_duplicates)
            validate_message(stage, value)
            if stage == 'plan' and value['task'] != TASK_ID:
                raise ValueError('task')
            if len(value['summary'].encode('utf-8')) > 1024 or key in value['summary'] or re.search(r'(?i)\b(?:sk-[a-z0-9_-]{12,}|bearer\s+\S+|-----begin [a-z ]*private key)', value['summary']):
                raise ValueError('sensitive or oversized')
            return value
        except BridgeError:
            raise
        except Exception:
            raise BridgeError('architect_response_invalid') from None
