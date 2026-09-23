"""Дедлайн, кеш и ограниченное число синхронных SDK-вызовов.

HTTP ждёт Future асинхронно. Зависший внешний вызов не удерживает HTTP-поток;
на процесс допускается не более llm_concurrency работающих daemon-потоков,
без очереди. Дедлайн прекращает ожидание, но не может принудительно прервать
чужой синхронный код: его слот остаётся занятым до завершения SDK-вызова.
"""
import asyncio
from concurrent.futures import Future, TimeoutError as FutureTimeout
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
import json
import os
from threading import Lock, Thread
from time import monotonic

from app.config import Settings
from app.observability import Metrics
from app.services.cache import ExplanationCache
from app.services.evidence import evidence_options, render_explanation
from app.services.prompts import MODEL, PROMPT_VERSION, SYSTEM_PROMPT
from app.services.provider import generate

TIMEOUT_WARNING = "Время ожидания объяснений истекло; показаны проверенные факты Python."


class ExplanationService:
    def __init__(self, *, client=None, settings: Settings):
        self.settings = settings
        self.metrics = Metrics()
        self.client = client
        self._owns_client = False
        self._client_lock = Lock()
        self._lock = Lock()
        self._inflight = {}
        self._closed = False
        self.cache = ExplanationCache(settings.cache_size, settings.cache_ttl)

    @staticmethod
    def _key(selected, request):
        # Содержимое профилей, включая цены/занятость, входит в ключ. При обновлении
        # данных прежняя цитата никогда не применяется к изменённому профилю.
        payload = dict(request=request, profiles=[asdict(p) for p in selected],
                       model=MODEL, temperature=0.0, prompt_version=PROMPT_VERSION,
                       system_prompt=SYSTEM_PROMPT)
        return sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    @staticmethod
    def _fallback(selected, request, options):
        result = {}
        for profile in selected:
            quote = options[profile.id][0] if options[profile.id] else None
            result[profile.id] = dict(
                explanation=render_explanation(profile, request, quote), explanation_source="python",
                evidence={"field": "description", "quote": quote} if quote else None)
        return result

    def _lookup(self, selected, request, deadline, use_llm):
        options = {p.id: evidence_options(p, selected) for p in selected}
        fallback = self._fallback(selected, request, options)
        if not use_llm:
            self.metrics.increment("offline")
            return fallback, None, (fallback, "Офлайн-режим: объяснения собраны на Python.")
        if self.client is None and not os.getenv("OPENAI_API_KEY"):
            self.metrics.increment("missing_key")
            return fallback, None, (fallback, "OPENAI_API_KEY не задан: объяснения собраны на Python.")
        if monotonic() >= deadline:
            self.metrics.increment("deadline_before_lookup")
            return fallback, None, (fallback, TIMEOUT_WARNING)
        key = self._key(selected, request)
        with self._lock:
            if self._closed:
                return fallback, None, (fallback, "Сервис объяснений завершает работу; показаны факты Python.")
            cached = self.cache.get(key)
            if cached is not None:
                self.metrics.increment("cache_hit")
                return fallback, None, (cached, None)
            self.metrics.increment("cache_miss")
            if key in self._inflight:
                self.metrics.increment("shared_wait")
                return fallback, self._inflight[key], None
            if len(self._inflight) >= self.settings.llm_concurrency:
                self.metrics.increment("saturated")
                return fallback, None, (fallback, "Сервис объяснений занят; показаны проверенные факты Python.")
            future = Future()
            self._inflight[key] = future
            worker = Thread(target=self._run, args=(key, future, selected, request, options, fallback, deadline),
                            name="explanation-request", daemon=True)
            try:
                worker.start()
            except RuntimeError:
                del self._inflight[key]
                return fallback, None, (fallback, "Не удалось запустить объяснение; показаны факты Python.")
        return fallback, future, None

    def _run(self, key, future, selected, request, options, fallback, deadline):
        try:
            with self._client_lock:
                if self.client is None:
                    from openai import OpenAI
                    self.client = OpenAI(timeout=7.0, max_retries=0)
                    self._owns_client = True
                client = self.client
            remaining = deadline - monotonic()
            if remaining <= 0:
                result = fallback, TIMEOUT_WARNING
            else:
                self.metrics.increment("provider_calls")
                started = monotonic()
                try:
                    result = generate(client, selected, request, options, fallback, timeout=min(7.0, remaining))
                    self.metrics.increment("provider_success" if result[1] is None else "provider_invalid")
                finally:
                    self.metrics.observe("provider", monotonic() - started)
        except Exception as exc:
            self.metrics.increment("provider_errors")
            result = fallback, f"LLM недоступна или ответ некорректен ({type(exc).__name__}); объяснения собраны на Python."
        if monotonic() >= deadline:
            self.metrics.increment("late_result")
            result = fallback, TIMEOUT_WARNING
        with self._lock:
            if result[1] is None and not self._closed:
                self.cache.put(key, result[0])
            # Future никогда не отменяется одним из ожидающих запросов.
            future.set_result(result)
            del self._inflight[key]
            should_close = self._closed and not self._inflight
        if should_close:
            self._close_client()

    def explain(self, selected, request, deadline, use_llm=True):
        fallback, future, immediate = self._lookup(selected, request, deadline, use_llm)
        if immediate is not None:
            return immediate
        try:
            return deepcopy(future.result(timeout=max(0, deadline - monotonic())))
        except FutureTimeout:
            self.metrics.increment("wait_timeout")
            return fallback, TIMEOUT_WARNING

    async def aexplain(self, selected, request, deadline, use_llm=True):
        fallback, future, immediate = self._lookup(selected, request, deadline, use_llm)
        if immediate is not None:
            return immediate
        try:
            # shield: уход одного клиента не отменяет общий запрос для остальных.
            return deepcopy(await asyncio.wait_for(
                asyncio.shield(asyncio.wrap_future(future)), timeout=max(0, deadline - monotonic())))
        except asyncio.TimeoutError:
            self.metrics.increment("wait_timeout")
            return fallback, TIMEOUT_WARNING

    def close(self):
        """Не ждём зависшую сеть. Последний worker закроет принадлежащий нам клиент."""
        with self._lock:
            self._closed = True
            idle = not self._inflight
        if idle:
            self._close_client()

    def _close_client(self):
        with self._client_lock:
            if self._owns_client and self.client is not None:
                self.client.close()
                self.client = None
                self._owns_client = False
