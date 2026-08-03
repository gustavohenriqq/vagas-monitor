"""
telegram_notifier.py — Envio de notificações via Telegram Bot API.

Usa parse_mode=HTML com escaping seguro. Não expõe o token em logs. Erros no
Telegram não interrompem a execução principal. Respeita um intervalo mínimo
entre envios para não tomar 429 em lotes grandes.
"""

from __future__ import annotations

import html
import logging
import time
from dataclasses import dataclass
from typing import Optional

import requests

from .models import (
    HYBRID,
    ONSITE,
    REMOTE,
    SENIORITY_UNKNOWN,
    JobPosting,
)

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"
REQUEST_TIMEOUT = 15
MAX_RETRIES = 3
RETRY_DELAY = 5
MIN_SEND_INTERVAL = 1.2
MAX_RATE_LIMIT_WAITS = 5

_WORKPLACE_LABEL = {
    REMOTE: "🏠 Remoto",
    HYBRID: "🔀 Híbrido",
    ONSITE: "🏢 Presencial",
}
_SENIORITY_LABEL = {
    "estagio": "Estágio",
    "junior": "Júnior",
    "pleno": "Pleno",
    "senior": "Sênior",
    "lead": "Lead/Especialista",
}
_PROVIDER_LABEL = {"gupy": "Gupy", "inhire": "inhire"}


def _esc(text: str) -> str:
    return html.escape(str(text or ""), quote=False)


def _truncate(text: str, max_len: int = 220) -> str:
    text = str(text or "").strip()
    return text if len(text) <= max_len else text[:max_len] + "…"


def _dica_para_erro(status_code: int, descricao: str) -> str:
    desc = descricao.lower()
    if "chat not found" in desc:
        return ("O bot nunca recebeu mensagem desse chat. Abra o Telegram, procure o bot "
                "e envie /start. Depois confira o TELEGRAM_CHAT_ID.")
    if "bot was blocked" in desc:
        return "O bot foi bloqueado por esse usuário. Desbloqueie o bot no Telegram."
    if "unauthorized" in desc or status_code == 401:
        return "TELEGRAM_BOT_TOKEN inválido ou revogado. Gere outro com o @BotFather."
    if "can't parse" in desc:
        return "HTML inválido para parse_mode=HTML. É bug de formatação."
    if "chat_id is empty" in desc:
        return "TELEGRAM_CHAT_ID não foi preenchido."
    return "Verifique TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID."


@dataclass
class Summary:
    new_count: int
    per_search: dict           # {search_name: count}
    per_provider: dict         # {provider: count}


def build_job_message(job: JobPosting, search_name: str = "") -> str:
    """Monta a mensagem HTML de uma vaga nova."""
    provider = _PROVIDER_LABEL.get(job.provider, job.provider)
    workplace = _WORKPLACE_LABEL.get(job.workplace_type, "📍 " + (job.location_label or "Local não informado"))
    seniority = _SENIORITY_LABEL.get(job.seniority, "")

    linhas = [
        "🚨 <b>NOVA VAGA</b>",
        "",
        f"💼 <b>{_esc(job.title)}</b>",
        f"🏢 <b>Empresa:</b> {_esc(job.company) or 'não informada'}",
    ]
    if seniority:
        linhas.append(f"🎯 <b>Nível:</b> {_esc(seniority)}")
    linhas.append(f"{workplace}   •   📡 {_esc(provider)}")
    if job.location_label and job.workplace_type != REMOTE:
        linhas.append(f"📍 <b>Local:</b> {_esc(job.location_label)}")
    if job.deadline:
        linhas.append(f"⏳ <b>Prazo:</b> {_esc(job.deadline)}")
    if search_name:
        linhas.append(f"🔎 <b>Busca:</b> {_esc(search_name)}")
    linhas.append("")
    linhas.append(f"🔗 {_esc(job.url)}")
    return "\n".join(linhas)


def build_summary_message(s: Summary) -> str:
    linhas = [f"📊 <b>RESUMO — {s.new_count} vaga(s) nova(s)</b>", ""]
    if s.per_provider:
        linhas.append("Por fonte:")
        for prov, n in s.per_provider.items():
            linhas.append(f"  • {_esc(_PROVIDER_LABEL.get(prov, prov))}: <b>{n}</b>")
    if s.per_search:
        linhas.append("")
        linhas.append("Por busca:")
        for name, n in s.per_search.items():
            linhas.append(f"  • {_esc(name)}: <b>{n}</b>")
    return "\n".join(linhas)


class TelegramNotifier:
    """Envia mensagens para um chat do Telegram via Bot API."""

    def __init__(self, bot_token: str, chat_id: str, min_send_interval: float = MIN_SEND_INTERVAL):
        self._token = bot_token
        self._chat_id = chat_id
        self._api_url = TELEGRAM_API_BASE.format(token=bot_token)
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})
        self._min_send_interval = max(min_send_interval, 0.0)
        self._last_send_at: Optional[float] = None

    def _throttle(self) -> None:
        if self._min_send_interval <= 0 or self._last_send_at is None:
            return
        espera = self._min_send_interval - (time.monotonic() - self._last_send_at)
        if espera > 0:
            time.sleep(espera)

    def _send(self, message: str) -> bool:
        payload = {
            "chat_id": self._chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        rate_limit_waits = 0
        attempt = 0
        while attempt < MAX_RETRIES:
            attempt += 1
            self._throttle()
            try:
                resp = self._session.post(self._api_url, json=payload, timeout=REQUEST_TIMEOUT)
                self._last_send_at = time.monotonic()

                if resp.status_code == 200 and resp.json().get("ok"):
                    logger.info("Mensagem Telegram enviada.")
                    return True
                if resp.status_code == 429:
                    rate_limit_waits += 1
                    if rate_limit_waits > MAX_RATE_LIMIT_WAITS:
                        logger.error("Rate limit persistente. Desistindo desta mensagem.")
                        return False
                    try:
                        retry_after = float(resp.json().get("parameters", {}).get("retry_after", RETRY_DELAY))
                    except (ValueError, TypeError, requests.exceptions.JSONDecodeError):
                        retry_after = RETRY_DELAY
                    logger.warning("Rate limit. Aguardando %.1fs.", retry_after)
                    time.sleep(retry_after)
                    attempt -= 1
                    continue

                try:
                    descricao = str(resp.json().get("description") or "sem descrição")
                except (ValueError, requests.exceptions.JSONDecodeError):
                    descricao = "resposta sem JSON"

                if 400 <= resp.status_code < 500:
                    logger.error("Erro %d do Telegram: %s | %s", resp.status_code, descricao,
                                 _dica_para_erro(resp.status_code, descricao))
                    return False
                logger.error("Erro HTTP %d (tentativa %d/%d): %s", resp.status_code, attempt, MAX_RETRIES, descricao)
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
            except requests.exceptions.RequestException as exc:
                self._last_send_at = time.monotonic()
                logger.error("Erro de conexão (tentativa %d/%d): %s", attempt, MAX_RETRIES, exc)
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
        logger.error("Falha definitiva ao enviar mensagem após %d tentativas.", MAX_RETRIES)
        return False

    def notify_job(self, job: JobPosting, search_name: str = "") -> bool:
        return self._send(build_job_message(job, search_name))

    def send_summary(self, summary: Summary, send_empty: bool = False) -> bool:
        if summary.new_count == 0 and not send_empty:
            logger.info("Resumo sem novidades e SEND_EMPTY_SUMMARY=false. Pulando.")
            return True
        return self._send(build_summary_message(summary))

    def close(self) -> None:
        self._session.close()


class _NoopNotifier:
    """Usado quando o Telegram não está configurado: só registra no log."""

    def notify_job(self, job: JobPosting, search_name: str = "") -> bool:
        logger.info("[noop] Vaga não notificada: %s (%s)", job.title, job.company)
        return True

    def send_summary(self, summary: Summary, send_empty: bool = False) -> bool:
        logger.info("[noop] Resumo não enviado: %d vagas novas.", summary.new_count)
        return True

    def close(self) -> None:
        pass


def build_notifier(bot_token: str, chat_id: str, min_send_interval: float = MIN_SEND_INTERVAL):
    if bot_token and chat_id:
        return TelegramNotifier(bot_token, chat_id, min_send_interval=min_send_interval)
    logger.warning("Telegram não configurado. Usando notifier noop.")
    return _NoopNotifier()
