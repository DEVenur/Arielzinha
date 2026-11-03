# -*- coding: utf-8 -*-
"""Discord Embedded Activity: autenticação e API somente de leitura."""
from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp
import tornado.web

DISCORD_API = "https://discord.com/api/v10"
SESSION_COOKIE = "activity_session"
SESSION_TTL = 24 * 60 * 60
_sessions: dict[str, dict] = {}
_control_timestamps: dict[str, float] = {}


def _json(handler: tornado.web.RequestHandler, payload: dict, status: int = 200):
    handler.set_status(status)
    handler.set_header("Content-Type", "application/json; charset=UTF-8")
    handler.set_header("Cache-Control", "no-store")
    handler.finish(json.dumps(payload, ensure_ascii=False))


class ActivityIndexHandler(tornado.web.RequestHandler):
    def get(self):
        if self.request.path.rstrip("/") == "/activity":
            return self.redirect("/activity/")
        index = Path(__file__).parent / "frontend" / "index.html"
        html = index.read_text(encoding="utf-8")
        html = html.replace("__DISCORD_CLIENT_ID__", os.environ.get("DISCORD_CLIENT_ID", ""))
        self.set_header("Content-Type", "text/html; charset=UTF-8")
        self.set_header("Cache-Control", "no-store")
        self.finish(html)


class ActivityAuthHandler(tornado.web.RequestHandler):
    async def post(self):
        client_id = os.environ.get("DISCORD_CLIENT_ID")
        client_secret = os.environ.get("DISCORD_CLIENT_SECRET")
        session_secret = os.environ.get("ACTIVITY_SESSION_SECRET")
        if not client_id or not client_secret or not session_secret:
            return _json(self, {"error": "Activity não configurada no servidor."}, 503)

        origin = self.request.headers.get("Origin")
        if not origin:
            return _json(self, {"error": "Origem da requisição ausente."}, 403)
        try:
            if urlsplit(origin).netloc.lower() != self.request.host.lower():
                return _json(self, {"error": "Origem não autorizada."}, 403)
        except ValueError:
            return _json(self, {"error": "Origem inválida."}, 403)

        try:
            body = json.loads(self.request.body or b"{}")
        except (TypeError, ValueError):
            return _json(self, {"error": "JSON inválido."}, 400)

        code = body.get("code") if isinstance(body, dict) else None
        if not isinstance(code, str) or not code or len(code) > 2048:
            return _json(self, {"error": "Código OAuth inválido."}, 400)

        timeout = aiohttp.ClientTimeout(total=12)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    f"{DISCORD_API}/oauth2/token",
                    data={
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "grant_type": "authorization_code",
                        "code": code,
                    },
                ) as response:
                    if response.status != 200:
                        return _json(self, {"error": "O Discord recusou a autorização."}, 401)
                    token_data = await response.json()

                access_token = token_data.get("access_token")
                if not access_token:
                    return _json(self, {"error": "Resposta OAuth inválida."}, 502)

                headers = {"Authorization": f"Bearer {access_token}"}
                async with session.get(f"{DISCORD_API}/users/@me", headers=headers) as response:
                    if response.status != 200:
                        return _json(self, {"error": "Não foi possível validar sua conta Discord."}, 401)
                    user = await response.json()

                async with session.get(f"{DISCORD_API}/users/@me/guilds", headers=headers) as response:
                    if response.status != 200:
                        return _json(self, {"error": "Não foi possível consultar seus servidores. Verifique o escopo guilds."}, 403)
                    user_guilds = await response.json()

        except (aiohttp.ClientError, TimeoutError):
            return _json(self, {"error": "Falha ao comunicar com o Discord."}, 502)

        if not isinstance(user_guilds, list) or not user.get("id"):
            return _json(self, {"error": "Resposta de identidade inválida."}, 502)

        now = time.time()
        for old_id, old_session in list(_sessions.items()):
            if old_session["expires_at"] <= now:
                _sessions.pop(old_id, None)

        session_id = secrets.token_urlsafe(32)
        _sessions[session_id] = {
            "user": {
                "id": str(user["id"]),
                "username": user.get("global_name") or user.get("username") or "Discord user",
                "avatar": user.get("avatar"),
            },
            "guild_ids": {str(g.get("id")) for g in user_guilds if isinstance(g, dict) and g.get("id")},
            "expires_at": now + SESSION_TTL,
        }
        self.set_secure_cookie(
            SESSION_COOKIE,
            session_id,
            expires_days=1,
            httponly=True,
            secure=True,
            samesite="None",
        )
        # O SDK exige o access token no cliente para concluir authenticate().
        # Ele não é gravado no cookie nem mantido no armazenamento do servidor.
        return _json(self, {"user": _sessions[session_id]["user"], "access_token": access_token})


class ActivityStateHandler(tornado.web.RequestHandler):
    def initialize(self, pool):
        self.pool = pool

    def get_current_session(self):
        raw = self.get_secure_cookie(SESSION_COOKIE)
        if not raw:
            return None
        try:
            session_id = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
        session = _sessions.get(session_id)
        if not session or session["expires_at"] <= time.time():
            _sessions.pop(session_id, None)
            return None
        return session

    async def get(self):
        if not os.environ.get("ACTIVITY_SESSION_SECRET"):
            return _json(self, {"error": "Activity não configurada no servidor."}, 503)
        session = self.get_current_session()
        if not session:
            return _json(self, {"error": "Sessão expirada. Abra a Activity novamente."}, 401)

        guilds = {}
        for bot in self.pool.get_all_bots():
            if not bot.is_ready() or not getattr(bot, "user", None):
                continue
            music = getattr(bot, "music", None)
            if music is None:
                continue

            for guild_id in session["guild_ids"]:
                guild = bot.get_guild(int(guild_id))
                if guild is None:
                    continue

                item = guilds.setdefault(str(guild.id), {
                    "id": str(guild.id),
                    "name": guild.name,
                    "icon": guild.icon.url if guild.icon else None,
                    "bots": [],
                    "player": None,
                })
                item["bots"].append({
                    "id": str(bot.user.id),
                    "name": bot.user.display_name,
                    "avatar": bot.user.display_avatar.url,
                })

                player = getattr(music, "players", {}).get(guild.id)
                if player is None:
                    continue

                track = getattr(player, "current", None)
                item["player"] = {
                    "bot_id": str(bot.user.id),
                    "playing": track is not None,
                    "paused": bool(getattr(player, "paused", False)),
                    "position": int(getattr(player, "position", 0) or 0),
                    "volume": int(getattr(player, "volume", 100) or 0),
                    "queue_length": len(getattr(player, "queue", ())),
                    "queue": [{
                        "title": str(getattr(queued, "title", "Desconhecida")),
                        "author": str(getattr(queued, "author", "")),
                        "duration": int(getattr(queued, "duration", 0) or 0),
                    } for queued in list(getattr(player, "queue", ()))[:10]],
                    "track": ({
                        "title": str(getattr(track, "title", "Desconhecida")),
                        "author": str(getattr(track, "author", "")),
                        "uri": getattr(track, "uri", None),
                        "artwork": getattr(track, "thumb", None),
                        "duration": int(getattr(track, "duration", 0) or 0),
                        "is_stream": bool(getattr(track, "is_stream", False)),
                    } if track else None),
                }

        return _json(self, {
            "user": session["user"],
            "guilds": sorted(guilds.values(), key=lambda guild: guild["name"].casefold()),
        })


class ActivityControlHandler(tornado.web.RequestHandler):
    def initialize(self, pool):
        self.pool = pool

    def _session(self):
        raw = self.get_secure_cookie(SESSION_COOKIE)
        if not raw:
            return None
        try:
            session_id = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
        session = _sessions.get(session_id)
        if not session or session["expires_at"] <= time.time():
            _sessions.pop(session_id, None)
            return None
        return session

    async def post(self):
        if not os.environ.get("ACTIVITY_SESSION_SECRET"):
            return _json(self, {"error": "Activity não configurada no servidor."}, 503)

        origin = self.request.headers.get("Origin")
        if not origin or urlsplit(origin).netloc.lower() != self.request.host.lower():
            return _json(self, {"error": "Origem não autorizada."}, 403)

        session = self._session()
        if not session:
            return _json(self, {"error": "Sessão expirada. Abra a Activity novamente."}, 401)

        try:
            data = json.loads(self.request.body or b"{}")
        except (TypeError, ValueError):
            return _json(self, {"error": "JSON inválido."}, 400)
        if not isinstance(data, dict):
            return _json(self, {"error": "Comando inválido."}, 400)

        guild_id = data.get("guild_id")
        bot_id = data.get("bot_id")
        action = data.get("action")
        if not all(isinstance(value, str) and value.isdigit() for value in (guild_id, bot_id)):
            return _json(self, {"error": "Servidor ou bot inválido."}, 400)
        if guild_id not in session["guild_ids"]:
            return _json(self, {"error": "Você não pertence a este servidor."}, 403)

        bot = next((b for b in self.pool.get_all_bots()
                    if getattr(getattr(b, "user", None), "id", None) == int(bot_id)), None)
        if bot is None or not bot.is_ready():
            return _json(self, {"error": "Bot indisponível."}, 404)
        guild = bot.get_guild(int(guild_id))
        if guild is None or guild.me is None or not guild.me.voice or not guild.me.voice.channel:
            return _json(self, {"error": "O bot não está conectado a um canal de voz."}, 409)

        voice_channel = guild.me.voice.channel
        if int(session["user"]["id"]) not in voice_channel.voice_states:
            return _json(self, {"error": "Entre no mesmo canal de voz do bot para controlar o player."}, 403)

        player = getattr(getattr(bot, "music", None), "players", {}).get(int(guild_id))
        if player is None or getattr(player, "is_closing", False) or getattr(player, "locked", False):
            return _json(self, {"error": "Player indisponível no momento."}, 409)

        now = time.monotonic()
        rate_key = f'{session["user"]["id"]}:{guild_id}'
        if now - _control_timestamps.get(rate_key, 0) < 0.35:
            return _json(self, {"error": "Aguarde um instante antes de enviar outro controle."}, 429)

        try:
            if action == "pause":
                value = data.get("value")
                if not isinstance(value, bool):
                    return _json(self, {"error": "Estado de pausa inválido."}, 400)
                await player.set_pause(value)

            elif action == "seek":
                value = data.get("value")
                track = getattr(player, "current", None)
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    return _json(self, {"error": "Posição inválida."}, 400)
                if track is None or getattr(track, "is_stream", False):
                    return _json(self, {"error": "Esta faixa não permite avançar ou retroceder."}, 409)
                duration = int(getattr(track, "duration", 0) or 0)
                if value > duration:
                    return _json(self, {"error": "Posição fora da duração da faixa."}, 400)
                await player.seek(value)

            elif action == "skip":
                if getattr(player, "current", None) is None:
                    return _json(self, {"error": "Não há faixa em reprodução."}, 409)
                if player.loop == "current":
                    player.loop = False
                try:
                    (player.current or player.last_track).info["extra"]["track_loops"] = 0
                except (AttributeError, KeyError, TypeError):
                    pass
                await player.track_end(ignore_track_loop=True)
                player.ignore_np_once = True
                await player.process_next()

            elif action == "volume":
                value = data.get("value")
                if isinstance(value, bool) or not isinstance(value, int) or not 5 <= value <= 150:
                    return _json(self, {"error": "O volume deve estar entre 5 e 150."}, 400)
                await player.set_volume(value)

            else:
                return _json(self, {"error": "Controle não suportado."}, 400)

        except Exception:
            return _json(self, {"error": "Não foi possível aplicar o controle ao player."}, 502)

        _control_timestamps[rate_key] = now
        return _json(self, {"ok": True})
