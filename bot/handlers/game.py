"""/impostor — classroom social deduction game (Among Us style).

One player creates a session and shares the code. Others join from their own
phones. Roles are DM'd privately. Offline players (no phone/internet) are added
by the host; their role cards appear on the host's screen behind a spoiler tag.
Voting is collected from each player's own chat; the host submits proxy votes
for offline players. Results are broadcast to all online players simultaneously.

State lives in context.bot_data["games"][code] — in memory, lost on restart,
which is fine for a classroom game.
"""
from __future__ import annotations

import asyncio
import logging
import random
import string
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from bot.middleware import require_auth

logger = logging.getLogger(__name__)

# ── constants ──────────────────────────────────────────────────────────────────

MIN_PLAYERS = 4
MAX_PLAYERS = 10
CODE_LENGTH = 4  # e.g. "4X7B"


# ── helpers ────────────────────────────────────────────────────────────────────

def _gen_code(existing: set[str]) -> str:
    chars = string.ascii_uppercase + string.digits
    while True:
        code = "".join(random.choices(chars, k=CODE_LENGTH))
        if code not in existing:
            return code


def _games(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any]:
    if "games" not in context.bot_data:
        context.bot_data["games"] = {}
    return context.bot_data["games"]


def _find_game_by_chat(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> tuple[str, dict] | None:
    """Return (code, game) for the game this chat_id is a participant in, or None."""
    for code, game in _games(context).items():
        if game["state"] == "ended":
            continue
        if game["host_chat_id"] == chat_id:
            return code, game
        for p in game["players"].values():
            if p["chat_id"] == chat_id:
                return code, game
    return None


def _find_player_by_chat(game: dict, chat_id: int) -> str | None:
    """Return the player name whose chat_id matches, or None."""
    for name, p in game["players"].items():
        if p["chat_id"] == chat_id:
            return name
    return None


def _alive_players(game: dict) -> list[str]:
    return [n for n, p in game["players"].items() if not p["eliminated"]]


def _alive_online(game: dict) -> list[str]:
    return [n for n, p in game["players"].items() if not p["eliminated"] and p["online"]]


def _votes_needed(game: dict) -> int:
    return len(_alive_players(game))


def _votes_cast(game: dict) -> int:
    return sum(
        1 for n, p in game["players"].items()
        if not p["eliminated"] and p["vote_this_round"] is not None
    )


def _tally(game: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    for p in game["players"].values():
        v = p["vote_this_round"]
        if v and v != "skip":
            counts[v] = counts.get(v, 0) + 1
    return counts


def _lobby_text(game: dict) -> str:
    lines = [f"🎮 Game `{game['code']}` — lobby ({len(game['players'])}/{MAX_PLAYERS} players)\n"]
    for name, p in game["players"].items():
        icon = "📱" if p["online"] else "👤"
        lines.append(f"  {icon} {name}")
    lines.append(f"\nImpostors: {game['impostor_count']}")
    lines.append("Host: use /impostor start when everyone is in.")
    return "\n".join(lines)


def _vote_keyboard(game: dict, exclude_name: str) -> InlineKeyboardMarkup:
    """Inline keyboard listing alive players the voter can vote for."""
    alive = [n for n in _alive_players(game) if n != exclude_name]
    rows = [[InlineKeyboardButton(name, callback_data=f"iv:{game['code']}:{name}")]
            for name in alive]
    rows.append([InlineKeyboardButton("⏭ Skip (abstain)", callback_data=f"iv:{game['code']}:__skip__")])
    return InlineKeyboardMarkup(rows)


async def _broadcast(context: ContextTypes.DEFAULT_TYPE, game: dict, text: str) -> None:
    """DM all alive online players simultaneously."""
    await asyncio.gather(*[
        context.bot.send_message(chat_id=p["chat_id"], text=text)
        for p in game["players"].values()
        if p["online"] and not p["eliminated"]
    ], return_exceptions=True)


async def _broadcast_all(context: ContextTypes.DEFAULT_TYPE, game: dict, text: str) -> None:
    """DM ALL online players (including eliminated), e.g. for game-end messages."""
    await asyncio.gather(*[
        context.bot.send_message(chat_id=p["chat_id"], text=text)
        for p in game["players"].values()
        if p["online"]
    ], return_exceptions=True)


# ── role card text ─────────────────────────────────────────────────────────────

def _role_card(name: str, role: str, game: dict) -> str:
    code = game["code"]
    round_no = game["round"]
    if role == "impostor":
        # Tell the impostor who their accomplices are (if any).
        partners = [
            n for n, p in game["players"].items()
            if p["role"] == "impostor" and n != name
        ]
        partner_line = f"Fellow impostor(s): {', '.join(partners)}" if partners else "You are the only impostor."
        return (
            f"🔴 YOU ARE THE IMPOSTOR\n\n"
            f"{partner_line}\n\n"
            f"Blend in. Don't get voted out.\n"
            f"Code: {code} — Round {round_no}"
        )
    else:
        n_imp = game["impostor_count"]
        imp_word = "impostor" if n_imp == 1 else "impostors"
        return (
            f"👥 YOU ARE A CREWMATE\n\n"
            f"There {'is' if n_imp == 1 else 'are'} {n_imp} {imp_word} among you.\n"
            f"Find them before it's too late.\n\n"
            f"Code: {code} — Round {round_no}"
        )


# ── win check ──────────────────────────────────────────────────────────────────

def _check_winner(game: dict) -> str | None:
    """Return 'crewmates', 'impostors', or None if game continues."""
    alive = _alive_players(game)
    alive_impostors = [n for n in alive if game["players"][n]["role"] == "impostor"]
    alive_crew = [n for n in alive if game["players"][n]["role"] == "crewmate"]

    if not alive_impostors:
        return "crewmates"
    if len(alive_impostors) >= len(alive_crew):
        return "impostors"
    return None


async def _resolve_vote(update_or_none: Update | None, context: ContextTypes.DEFAULT_TYPE, game: dict) -> None:
    """Tally votes, eliminate the plurality target, broadcast result, check win."""
    tally = _tally(game)
    alive = _alive_players(game)

    if not tally:
        # All abstained.
        eliminated = None
        result_line = "Nobody was eliminated (everyone abstained)."
    else:
        max_votes = max(tally.values())
        top = [n for n, v in tally.items() if v == max_votes]
        if len(top) > 1:
            # Tie → random among tied players.
            eliminated = random.choice(top)
            tie_note = f"Tie between {', '.join(top)} — random draw: "
        else:
            eliminated = top[0]
            tie_note = ""

        role = game["players"][eliminated]["role"]
        role_label = "🔴 IMPOSTOR" if role == "impostor" else "🔵 CREWMATE"
        game["players"][eliminated]["eliminated"] = True
        result_line = f"{tie_note}**{eliminated}** was eliminated ({max_votes} vote{'s' if max_votes != 1 else ''}).\nThey were: {role_label}"

    # Vote breakdown (anonymous — just counts).
    breakdown = "  " + ", ".join(f"{n}: {v}" for n, v in sorted(tally.items(), key=lambda x: -x[1])) if tally else "  (no votes)"

    winner = _check_winner(game)

    remaining = len(_alive_players(game))
    text = (
        f"🗳 Vote result — Round {game['round']}\n\n"
        f"{result_line}\n\n"
        f"Vote tally:\n{breakdown}\n\n"
    )

    if winner:
        game["state"] = "ended"
        if winner == "crewmates":
            text += "🎉 CREWMATES WIN! All impostors have been found."
        else:
            text += "😈 IMPOSTORS WIN! They can no longer be voted out."
        await _broadcast_all(context, game, text)
        # Also send to host's chat for offline player awareness.
        await context.bot.send_message(chat_id=game["host_chat_id"], text=text)
    else:
        # Start next round.
        game["round"] += 1
        for p in game["players"].values():
            p["vote_this_round"] = None

        alive_count = len(_alive_players(game))
        text += f"{remaining} players remain. Round {game['round']} begins — discuss!"
        await _broadcast(context, game, text)
        await context.bot.send_message(chat_id=game["host_chat_id"], text=text)


# ── command handlers ───────────────────────────────────────────────────────────

@require_auth
async def impostor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Single entry point — dispatches on context.args[0]."""
    args = context.args or []
    sub = args[0].lower() if args else ""

    dispatch = {
        "new":     _cmd_new,
        "join":    _cmd_join,
        "add":     _cmd_add,
        "players": _cmd_players,
        "start":   _cmd_start,
        "vote":    _cmd_vote,
        "skip":    _cmd_skip,
        "status":  _cmd_status,
        "role":    _cmd_role,
        "end":     _cmd_end,
    }

    fn = dispatch.get(sub)
    if fn is None:
        await update.effective_message.reply_text(
            "Unknown subcommand. Try:\n"
            "/impostor new — create a game\n"
            "/impostor join <code> <name> — join a game\n"
            "/impostor add <name> — add an offline player (host)\n"
            "/impostor players — see who has joined\n"
            "/impostor start — begin the game (host)\n"
            "/impostor vote <name> — vote to eliminate\n"
            "/impostor skip — abstain from voting\n"
            "/impostor status — check vote progress\n"
            "/impostor role — see your role card again\n"
            "/impostor end — abort the game (host)"
        )
        return

    await fn(update, context, args[1:])


async def _cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE, args: list[str]) -> None:
    chat_id = update.effective_chat.id
    games = _games(context)

    # Parse optional impostor count.
    try:
        n_impostors = max(1, int(args[0])) if args else 1
    except ValueError:
        n_impostors = 1

    # Clean up any existing session this chat was hosting.
    to_remove = [c for c, g in games.items() if g["host_chat_id"] == chat_id]
    for c in to_remove:
        del games[c]

    code = _gen_code(set(games.keys()))
    games[code] = {
        "code": code,
        "host_chat_id": chat_id,
        "state": "lobby",
        "impostor_count": n_impostors,
        "round": 1,
        "players": {},
    }

    await update.effective_message.reply_text(
        f"🎮 Game created!\n\n"
        f"Code: `{code}`\n"
        f"Impostors: {n_impostors}\n\n"
        f"Share the code. Players join with:\n"
        f"/impostor join {code} <YourName>\n\n"
        f"No phone? Use /impostor add <name> to add them here.\n"
        f"Start with /impostor start when everyone is in (min {MIN_PLAYERS}).",
        parse_mode="Markdown",
    )


async def _cmd_join(update: Update, context: ContextTypes.DEFAULT_TYPE, args: list[str]) -> None:
    if len(args) < 2:
        await update.effective_message.reply_text(
            "Usage: /impostor join <code> <name>"
        )
        return

    code = args[0].upper()
    name = " ".join(args[1:]).strip()
    chat_id = update.effective_chat.id
    games = _games(context)

    if code not in games:
        await update.effective_message.reply_text(
            f"No game found with code {code}. Check the code and try again."
        )
        return

    game = games[code]

    if game["state"] != "lobby":
        await update.effective_message.reply_text("That game has already started.")
        return

    if len(game["players"]) >= MAX_PLAYERS:
        await update.effective_message.reply_text(f"Game is full ({MAX_PLAYERS} players max).")
        return

    if name in game["players"]:
        await update.effective_message.reply_text(
            f'The name "{name}" is already taken. Pick a different one.'
        )
        return

    # Check if this chat_id is already in the game under a different name.
    existing = _find_player_by_chat(game, chat_id)
    if existing:
        await update.effective_message.reply_text(
            f'You are already in this game as "{existing}".'
        )
        return

    game["players"][name] = {
        "chat_id": chat_id,
        "online": True,
        "role": None,
        "eliminated": False,
        "vote_this_round": None,
    }

    await update.effective_message.reply_text(
        f"✅ You joined game `{code}` as **{name}**.\n\n"
        + _lobby_text(game),
        parse_mode="Markdown",
    )

    # Notify host.
    if game["host_chat_id"] != chat_id:
        await context.bot.send_message(
            chat_id=game["host_chat_id"],
            text=f"📱 {name} joined.\n\n" + _lobby_text(game),
        )


async def _cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE, args: list[str]) -> None:
    """Host adds an offline player by name."""
    chat_id = update.effective_chat.id
    result = _find_game_by_chat(context, chat_id)

    if result is None:
        await update.effective_message.reply_text(
            "You don't have an active game. Create one with /impostor new."
        )
        return

    code, game = result

    if game["host_chat_id"] != chat_id:
        await update.effective_message.reply_text("Only the host can add offline players.")
        return

    if game["state"] != "lobby":
        await update.effective_message.reply_text("Can't add players after the game has started.")
        return

    if not args:
        await update.effective_message.reply_text("Usage: /impostor add <name>")
        return

    name = " ".join(args).strip()

    if len(game["players"]) >= MAX_PLAYERS:
        await update.effective_message.reply_text(f"Game is full ({MAX_PLAYERS} players max).")
        return

    if name in game["players"]:
        await update.effective_message.reply_text(
            f'The name "{name}" is already taken.'
        )
        return

    game["players"][name] = {
        "chat_id": None,
        "online": False,
        "role": None,
        "eliminated": False,
        "vote_this_round": None,
    }

    await update.effective_message.reply_text(
        f"👤 Added offline player **{name}**.\n\n" + _lobby_text(game),
        parse_mode="Markdown",
    )


async def _cmd_players(update: Update, context: ContextTypes.DEFAULT_TYPE, args: list[str]) -> None:
    chat_id = update.effective_chat.id
    result = _find_game_by_chat(context, chat_id)

    if result is None:
        await update.effective_message.reply_text(
            "You are not in any active game. Join one with /impostor join <code> <name>."
        )
        return

    _, game = result
    await update.effective_message.reply_text(_lobby_text(game), parse_mode="Markdown")


async def _cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE, args: list[str]) -> None:
    chat_id = update.effective_chat.id
    result = _find_game_by_chat(context, chat_id)

    if result is None or _games(context).get((result or [None])[0], {}).get("host_chat_id") != chat_id:
        await update.effective_message.reply_text(
            "Only the host can start the game."
        )
        return

    code, game = result

    if game["host_chat_id"] != chat_id:
        await update.effective_message.reply_text("Only the host can start the game.")
        return

    if game["state"] != "lobby":
        await update.effective_message.reply_text("The game is already running.")
        return

    total = len(game["players"])
    if total < MIN_PLAYERS:
        await update.effective_message.reply_text(
            f"Need at least {MIN_PLAYERS} players to start. Currently: {total}."
        )
        return

    if game["impostor_count"] >= total:
        await update.effective_message.reply_text(
            f"Too many impostors ({game['impostor_count']}) for {total} players."
        )
        return

    # Assign roles.
    names = list(game["players"].keys())
    impostors = set(random.sample(names, game["impostor_count"]))
    for name in names:
        game["players"][name]["role"] = "impostor" if name in impostors else "crewmate"

    game["state"] = "active"

    await update.effective_message.reply_text(
        f"🎮 Game `{code}` is starting! {total} players, {game['impostor_count']} impostor(s).\n\n"
        "Sending role cards now...",
        parse_mode="Markdown",
    )

    # Send role cards — DM for online players, spoiler on host's chat for offline.
    offline_cards = []
    online_tasks = []

    for name, player in game["players"].items():
        card = _role_card(name, player["role"], game)
        if player["online"]:
            online_tasks.append(
                context.bot.send_message(chat_id=player["chat_id"], text=card)
            )
        else:
            offline_cards.append((name, card))

    await asyncio.gather(*online_tasks, return_exceptions=True)

    for name, card in offline_cards:
        spoiler = f"||{card}||"
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"📵 Show this to **{name}** privately, then let them tap to reveal:\n\n{spoiler}",
            parse_mode="Markdown",
        )

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "✅ All role cards sent.\n\n"
            "Discuss in person, then everyone votes:\n"
            "/impostor vote <name> — vote to eliminate\n"
            "/impostor skip — abstain\n"
            "/impostor status — check how many have voted"
        ),
    )


async def _cmd_vote(update: Update, context: ContextTypes.DEFAULT_TYPE, args: list[str]) -> None:
    chat_id = update.effective_chat.id
    result = _find_game_by_chat(context, chat_id)

    if result is None:
        await update.effective_message.reply_text("You are not in any active game.")
        return

    code, game = result

    if game["state"] != "active":
        await update.effective_message.reply_text("No vote is in progress right now.")
        return

    is_host = game["host_chat_id"] == chat_id

    # Two forms:
    #   /impostor vote <target>          — direct vote (online player)
    #   /impostor vote <voter> <target>  — proxy vote (host only, for offline player)
    if len(args) == 2 and is_host:
        # Proxy vote: first arg is the offline player name, second is the target.
        voter_name = args[0]
        target_name = args[1]

        if voter_name not in game["players"]:
            await update.effective_message.reply_text(f'No player named "{voter_name}" in this game.')
            return
        voter = game["players"][voter_name]
        if voter["online"]:
            await update.effective_message.reply_text(
                f'"{voter_name}" is an online player — they must vote from their own phone.'
            )
            return
        if voter["eliminated"]:
            await update.effective_message.reply_text(f'"{voter_name}" has already been eliminated.')
            return
    elif len(args) == 1:
        # Direct vote.
        voter_name = _find_player_by_chat(game, chat_id)
        if voter_name is None:
            await update.effective_message.reply_text("You are not a player in this game.")
            return
        if game["players"][voter_name]["eliminated"]:
            await update.effective_message.reply_text("You have been eliminated and cannot vote.")
            return
        target_name = args[0]
    else:
        await update.effective_message.reply_text(
            "Usage:\n"
            "/impostor vote <name> — vote to eliminate someone\n"
            "/impostor vote <offline-player> <target> — proxy vote (host only)"
        )
        return

    if target_name not in game["players"]:
        await update.effective_message.reply_text(f'No player named "{target_name}" in this game.')
        return
    if game["players"][target_name]["eliminated"]:
        await update.effective_message.reply_text(f'"{target_name}" is already eliminated.')
        return
    if target_name == voter_name:
        await update.effective_message.reply_text("You can't vote for yourself.")
        return

    game["players"][voter_name]["vote_this_round"] = target_name
    cast = _votes_cast(game)
    needed = _votes_needed(game)

    await update.effective_message.reply_text(
        f"✅ Vote recorded: {voter_name} → {target_name}.\n"
        f"Votes in: {cast}/{needed}"
    )

    if cast >= needed:
        await _resolve_vote(update, context, game)


async def _cmd_vote_inline(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline vote button taps."""
    query = update.callback_query
    await query.answer()

    _, code, target_name = query.data.split(":", 2)
    chat_id = query.message.chat_id
    games = _games(context)

    if code not in games:
        await query.edit_message_text("This game no longer exists.")
        return

    game = games[code]
    if game["state"] != "active":
        await query.edit_message_text("Voting is not currently open.")
        return

    voter_name = _find_player_by_chat(game, chat_id)
    if voter_name is None:
        await query.answer("You are not a player in this game.", show_alert=True)
        return
    if game["players"][voter_name]["eliminated"]:
        await query.answer("You have been eliminated.", show_alert=True)
        return
    if game["players"][voter_name]["vote_this_round"] is not None:
        await query.answer("You have already voted.", show_alert=True)
        return

    if target_name == "__skip__":
        game["players"][voter_name]["vote_this_round"] = "skip"
        vote_label = "abstained"
    else:
        if target_name not in game["players"] or game["players"][target_name]["eliminated"]:
            await query.answer("That player is no longer in the game.", show_alert=True)
            return
        game["players"][voter_name]["vote_this_round"] = target_name
        vote_label = f"voted for {target_name}"

    cast = _votes_cast(game)
    needed = _votes_needed(game)
    await query.edit_message_text(
        f"✅ {voter_name} {vote_label}.\nVotes in: {cast}/{needed}"
    )

    if cast >= needed:
        await _resolve_vote(None, context, game)


async def _cmd_skip(update: Update, context: ContextTypes.DEFAULT_TYPE, args: list[str]) -> None:
    chat_id = update.effective_chat.id
    result = _find_game_by_chat(context, chat_id)

    if result is None:
        await update.effective_message.reply_text("You are not in any active game.")
        return

    code, game = result

    if game["state"] != "active":
        await update.effective_message.reply_text("No vote is in progress right now.")
        return

    is_host = game["host_chat_id"] == chat_id

    # /impostor skip [offline-player-name]
    if args and is_host:
        voter_name = " ".join(args).strip()
        if voter_name not in game["players"]:
            await update.effective_message.reply_text(f'No player named "{voter_name}".')
            return
        if game["players"][voter_name]["online"]:
            await update.effective_message.reply_text(
                f'"{voter_name}" is online — they must skip from their own phone.'
            )
            return
    else:
        voter_name = _find_player_by_chat(game, chat_id)
        if voter_name is None:
            await update.effective_message.reply_text("You are not a player in this game.")
            return

    if game["players"][voter_name]["eliminated"]:
        await update.effective_message.reply_text(f'"{voter_name}" is already eliminated.')
        return
    if game["players"][voter_name]["vote_this_round"] is not None:
        await update.effective_message.reply_text(f'"{voter_name}" has already voted this round.')
        return

    game["players"][voter_name]["vote_this_round"] = "skip"
    cast = _votes_cast(game)
    needed = _votes_needed(game)

    await update.effective_message.reply_text(
        f"⏭ {voter_name} abstained. Votes in: {cast}/{needed}"
    )

    if cast >= needed:
        await _resolve_vote(update, context, game)


async def _cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE, args: list[str]) -> None:
    chat_id = update.effective_chat.id
    result = _find_game_by_chat(context, chat_id)

    if result is None:
        await update.effective_message.reply_text("You are not in any active game.")
        return

    _, game = result

    if game["state"] == "lobby":
        await update.effective_message.reply_text(_lobby_text(game), parse_mode="Markdown")
        return

    if game["state"] == "ended":
        await update.effective_message.reply_text("This game has ended.")
        return

    cast = _votes_cast(game)
    needed = _votes_needed(game)
    alive = _alive_players(game)

    lines = [
        f"🎮 Game `{game['code']}` — Round {game['round']}",
        f"Alive: {', '.join(alive)}",
        f"Votes in: {cast}/{needed}",
    ]

    # Show who still needs to vote (names only — not who they voted for).
    waiting = [
        n for n in alive
        if game["players"][n]["vote_this_round"] is None
    ]
    if waiting:
        lines.append(f"Waiting on: {', '.join(waiting)}")

    await update.effective_message.reply_text("\n".join(lines), parse_mode="Markdown")


async def _cmd_role(update: Update, context: ContextTypes.DEFAULT_TYPE, args: list[str]) -> None:
    """Re-display the player's own role card."""
    chat_id = update.effective_chat.id
    result = _find_game_by_chat(context, chat_id)

    if result is None:
        await update.effective_message.reply_text("You are not in any active game.")
        return

    _, game = result

    if game["state"] == "lobby":
        await update.effective_message.reply_text("The game hasn't started yet.")
        return

    player_name = _find_player_by_chat(game, chat_id)
    if player_name is None:
        await update.effective_message.reply_text("You are not a player in this game.")
        return

    card = _role_card(player_name, game["players"][player_name]["role"], game)
    await update.effective_message.reply_text(card)


async def _cmd_end(update: Update, context: ContextTypes.DEFAULT_TYPE, args: list[str]) -> None:
    chat_id = update.effective_chat.id
    result = _find_game_by_chat(context, chat_id)

    if result is None:
        await update.effective_message.reply_text("You don't have an active game.")
        return

    code, game = result

    if game["host_chat_id"] != chat_id:
        await update.effective_message.reply_text("Only the host can end the game.")
        return

    game["state"] = "ended"
    await _broadcast_all(context, game, "🛑 The host ended the game.")
    await update.effective_message.reply_text(f"Game `{code}` ended.", parse_mode="Markdown")


# ── handler registration ───────────────────────────────────────────────────────

def build_handlers() -> list:
    return [
        CommandHandler("impostor", impostor),
        CallbackQueryHandler(_cmd_vote_inline, pattern=r"^iv:"),
    ]
