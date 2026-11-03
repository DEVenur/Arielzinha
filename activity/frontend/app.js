import { DiscordSDK } from "https://esm.sh/@discord/embedded-app-sdk@2.5.0";

const statusNode = document.querySelector("#status");
const contentNode = document.querySelector("#content");
const guildsNode = document.querySelector("#guilds");
const emptyNode = document.querySelector("#empty");
const profileNode = document.querySelector("#profile");
const refreshButton = document.querySelector("#refresh");

const showError = (message, retry = false) => {
  statusNode.innerHTML = "";
  const text = document.createElement("p");
  text.className = "error";
  text.textContent = message;
  statusNode.append(text);
  if (retry) {
    const button = document.createElement("button");
    button.className = "secondary";
    button.textContent = "Tentar novamente";
    button.addEventListener("click", () => location.reload());
    statusNode.append(button);
  }
};

async function authenticate(sdk, clientId) {
  const { code } = await sdk.commands.authorize({
    client_id: clientId,
    response_type: "code",
    state: crypto.randomUUID(),
    prompt: "none",
    scope: ["identify", "guilds"],
  });

  const response = await fetch("/activity/api/auth", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify({ code }),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "Falha na autenticação.");
  await sdk.commands.authenticate({ access_token: result.access_token });
  return result.user;
}

function renderGuild(guild) {
  const card = document.createElement("article");
  card.className = "guild-card";
  const head = document.createElement("div");
  head.className = "guild-head";
  if (guild.icon) {
    const icon = document.createElement("img");
    icon.className = "guild-icon";
    icon.src = guild.icon;
    icon.alt = "";
    head.append(icon);
  } else {
    const icon = document.createElement("div");
    icon.className = "guild-icon";
    icon.textContent = guild.name.slice(0, 1).toUpperCase();
    head.append(icon);
  }
  const info = document.createElement("div");
  info.style.minWidth = "0";
  const name = document.createElement("div");
  name.className = "guild-name";
  name.textContent = guild.name;
  info.append(name);
  const bots = document.createElement("div");
  bots.className = "bot-list";
  for (const bot of guild.bots) {
    const chip = document.createElement("span");
    chip.className = "bot-chip";
    chip.textContent = bot.name;
    bots.append(chip);
  }
  info.append(bots);
  head.append(info);
  card.append(head);

  if (guild.player?.track) {
    const track = document.createElement("div");
    track.className = "track";
    const title = document.createElement("div");
    title.className = "track-title";
    title.textContent = guild.player.track.title;
    const author = document.createElement("div");
    author.className = "track-author";
    author.textContent = guild.player.track.author || "Artista desconhecido";
    track.append(title, author);
    const controls = document.createElement("div");
    controls.className = "controls";
    const pause = document.createElement("button");
    pause.className = "secondary";
    pause.textContent = guild.player.paused ? "Retomar" : "Pausar";
    pause.addEventListener("click", () => sendControl(guild, "pause", !guild.player.paused));
    controls.append(pause);

    if (!guild.player.track.is_stream && guild.player.track.duration > 0) {
      const seek = document.createElement("input");
      seek.type = "range";
      seek.min = "0";
      seek.max = String(guild.player.track.duration);
      seek.step = "1000";
      seek.value = String(Math.min(guild.player.position, guild.player.track.duration));
      seek.setAttribute("aria-label", "Posição da música");
      seek.addEventListener("change", () => sendControl(guild, "seek", Number(seek.value)));
      controls.append(seek);
    }

    const volume = document.createElement("input");
    volume.type = "range";
    volume.min = "5";
    volume.max = "150";
    volume.step = "5";
    volume.value = String(guild.player.volume);
    volume.setAttribute("aria-label", "Volume");
    volume.addEventListener("change", () => sendControl(guild, "volume", Number(volume.value)));
    controls.append(volume);

    const hint = document.createElement("small");
    hint.className = "control-hint";
    hint.textContent = "Entre no canal de voz do bot para usar os controles.";
    controls.append(hint);
    track.append(controls);

    const meta = document.createElement("div");
    meta.className = "player-meta";
    const state = document.createElement("span");
    state.textContent = guild.player.paused ? "Pausado" : "Em reprodução";
    const queue = document.createElement("span");
    queue.textContent = `${guild.player.queue_length} na fila`;
    meta.append(state, queue);
    track.append(meta);
    card.append(track);
  } else {
    const idle = document.createElement("div");
    idle.className = "idle";
    idle.textContent = "Nenhuma música em reprodução neste servidor.";
    card.append(idle);
  }
  return card;
}

async function sendControl(guild, action, value) {
  try {
    const response = await fetch("/activity/api/control", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({
        guild_id: guild.id,
        bot_id: guild.player.bot_id,
        action,
        value,
      }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Controle não aplicado.");
    await loadState();
  } catch (error) {
    showError(error?.message || "Falha ao controlar o player.", true);
  }
}

async function loadState() {
  const response = await fetch("/activity/api/state", { credentials: "same-origin", cache: "no-store" });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Não foi possível carregar os servidores.");
  guildsNode.replaceChildren(...data.guilds.map(renderGuild));
  emptyNode.classList.toggle("hidden", data.guilds.length !== 0);
  profileNode.textContent = data.user.username;
  profileNode.classList.remove("hidden");
  contentNode.classList.remove("hidden");
  statusNode.classList.add("hidden");
}

async function start() {
  const clientId = document.documentElement.dataset.clientId;
  if (!clientId) {
    showError("Configure DISCORD_CLIENT_ID no ambiente do servidor.");
    return;
  }
  try {
    const sdk = new DiscordSDK(clientId);
    await sdk.ready();
    await authenticate(sdk, clientId);
    await loadState();
  } catch (error) {
    showError(error?.message || "Não foi possível iniciar a Activity.", true);
  }
}

refreshButton.addEventListener("click", async () => {
  refreshButton.disabled = true;
  try { await loadState(); }
  catch (error) { showError(error?.message || "Falha ao atualizar.", true); }
  finally { refreshButton.disabled = false; }
});

start();
