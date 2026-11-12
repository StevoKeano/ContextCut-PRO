#!/usr/bin/env python3
"""Independent behavioural checks for the token-wyrm workspace."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
import traceback
from collections import deque
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

ROOT = Path.cwd().resolve()
sys.path.insert(0, str(ROOT))

FAILURES: list[tuple[str, str]] = []


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_check(name: str, check) -> None:
    try:
        check()
    except Exception as exc:
        FAILURES.append((name, str(exc)))
        print(f"FAIL {name}: {exc}")
        return
    print(f"PASS {name}")


def value(tile) -> str:
    name = getattr(tile, "name", None)
    if name:
        return str(name)
    return str(getattr(tile, "value", tile))


def is_walkable(game_map, position) -> bool:
    return value(game_map.get_tile(position)) in {"FLOOR", ".", "STAIRS_DOWN", ">"}


def is_stairs(game_map, position) -> bool:
    return value(game_map.get_tile(position)) in {"STAIRS_DOWN", ">"}


def fresh_engine(seed: int = 7):
    from token_wyrm.engine import GameEngine

    engine = GameEngine(seed=seed)
    engine.start_new_game()
    return engine


def snapshot(engine) -> dict:
    game_map = engine.game_map
    return {
        "tiles": [[value(tile) for tile in row] for row in game_map.tiles],
        "player": (engine.player.position.x, engine.player.position.y),
        "entities": sorted(
            (
                value(getattr(entity, "entity_type", "")),
                getattr(entity, "name", ""),
                entity.position.x,
                entity.position.y,
                getattr(entity, "hp", 0),
            )
            for entity in game_map.entities
        ),
        "items": sorted(
            (
                value(item.item_type),
                item.position.x,
                item.position.y,
            )
            for item in game_map.items
        ),
    }


def reachable_positions(game_map, start) -> set[tuple[int, int]]:
    from token_wyrm.models import Position

    seen = {(start.x, start.y)}
    queue = deque([(start.x, start.y)])
    while queue:
        x, y = queue.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            next_pos = Position(x + dx, y + dy)
            key = (next_pos.x, next_pos.y)
            if key in seen or not is_walkable(game_map, next_pos):
                continue
            seen.add(key)
            queue.append(key)
    return seen


def find_stairs(game_map):
    from token_wyrm.models import Position

    for y, row in enumerate(game_map.tiles):
        for x, tile in enumerate(row):
            if value(tile) in {"STAIRS_DOWN", ">"}:
                return Position(x, y)
    return None


def is_boss(entity) -> bool:
    if getattr(entity, "is_boss", False):
        return True
    name = str(getattr(entity, "name", "")).lower()
    return "boss" in name or "token wyrm" in name or "wyrm" in name


def check_help() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "token_wyrm", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    require(result.returncode == 0, f"--help exited {result.returncode}: {result.stderr}")
    output = result.stdout + result.stderr
    for flag in ("--seed", "--load", "--no-color", "--self-check"):
        require(flag in output, f"--help does not document {flag}")


def check_self_check() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "token_wyrm", "--seed", "7", "--self-check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    require(result.returncode == 0, f"self-check exited {result.returncode}: {result.stderr}")


def check_determinism() -> None:
    first = fresh_engine(7)
    second = fresh_engine(7)
    require(snapshot(first) == snapshot(second), "same seed produced different layouts")
    other = fresh_engine(8)
    require(snapshot(first) != snapshot(other), "different seeds produced identical layouts")


def check_map_and_reachability() -> None:
    engine = fresh_engine(7)
    game_map = engine.game_map
    require(game_map.width > 0 and game_map.height > 0, "map has no dimensions")
    require(len(game_map.tiles) == game_map.height, "map height mismatch")
    require(all(len(row) == game_map.width for row in game_map.tiles), "map is not rectangular")
    tiles = {value(tile) for row in game_map.tiles for tile in row}
    require(tiles & {"FLOOR", "."}, "map has no floor tiles")
    require(tiles & {"WALL", "#"}, "map has no wall tiles")
    require(is_walkable(game_map, engine.player.position), "player starts inside a wall")
    require(not is_stairs(game_map, engine.player.position), "player starts on stairs")

    reachable = reachable_positions(game_map, engine.player.position)
    stairs = find_stairs(game_map)
    require(stairs is not None, "map has no stairs")
    require((stairs.x, stairs.y) in reachable, "stairs are not reachable")

    for entity in game_map.entities:
        require(is_walkable(game_map, entity.position), f"{entity.name} spawned in a wall")
        if entity is not engine.player:
            require(not is_stairs(game_map, entity.position), f"{entity.name} spawned on stairs")
            require((entity.position.x, entity.position.y) in reachable, f"{entity.name} is unreachable")
    for item in game_map.items:
        require(is_walkable(game_map, item.position), f"{item.name} spawned in a wall")
        require(not is_stairs(game_map, item.position), f"{item.name} spawned on stairs")
        require((item.position.x, item.position.y) in reachable, f"{item.name} is unreachable")


def check_movement_and_collision() -> None:
    from token_wyrm.models import Position

    directions = {"UP": (0, -1), "DOWN": (0, 1), "LEFT": (-1, 0), "RIGHT": (1, 0)}
    engine = fresh_engine(7)
    game_map = engine.game_map
    origins = []
    for y, row in enumerate(game_map.tiles):
        for x, _ in enumerate(row):
            position = Position(x, y)
            if not is_walkable(game_map, position):
                continue
            for name, (dx, dy) in directions.items():
                neighbour = Position(x + dx, y + dy)
                if not is_walkable(game_map, neighbour) and game_map.get_entity_at(neighbour) is None:
                    origins.append((position, name))
                    break
            if origins:
                break
        if origins:
            break
    require(origins, "could not find a floor tile next to a wall")
    position, direction = origins[0]
    engine.player.position = position
    before = engine.player.position.copy()
    engine.move_player(direction)
    require(engine.player.position == before, "player walked through a wall")

    moved = False
    for y, row in enumerate(game_map.tiles):
        for x, _ in enumerate(row):
            position = Position(x, y)
            if not is_walkable(game_map, position):
                continue
            for name, (dx, dy) in directions.items():
                neighbour = Position(x + dx, y + dy)
                if (
                    is_walkable(game_map, neighbour)
                    and game_map.get_entity_at(neighbour) is None
                    and game_map.get_item_at(neighbour) is None
                ):
                    engine.player.position = position
                    engine.move_player(name)
                    moved = engine.player.position == neighbour
                    if moved:
                        break
            if moved:
                break
        if moved:
            break
    require(moved, "player could not move onto an adjacent floor tile")


def check_enemy_turns() -> None:
    from token_wyrm.models import Enemy, EntityType, Position

    engine = fresh_engine(7)
    game_map = engine.game_map
    placed = False
    for y, row in enumerate(game_map.tiles):
        for x, _ in enumerate(row):
            first = Position(x, y)
            if not is_walkable(game_map, first) or game_map.get_entity_at(first) is not None:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                second = Position(x + dx, y + dy)
                if not is_walkable(game_map, second) or game_map.get_entity_at(second) is not None:
                    continue
                engine.player.position = first
                enemy = Enemy(position=second, enemy_type=EntityType.GOBLIN)
                game_map.add_entity(enemy)
                before = (engine.player.hp, enemy.position.x, enemy.position.y)
                engine.wait_turn()
                after = (engine.player.hp, enemy.position.x, enemy.position.y)
                require(after != before, "waiting did not let an adjacent enemy act")
                placed = True
                break
            if placed:
                break
        if placed:
            break
    require(placed, "could not place an enemy next to the player")


def check_combat() -> None:
    from token_wyrm.combat import attack, resolve_combat
    from token_wyrm.models import Enemy, EntityType, MessageLog, Player, Position

    player = Player(position=Position(0, 0))
    enemy = Enemy(position=Position(1, 1), enemy_type=EntityType.GOBLIN)
    enemy.hp = enemy.max_hp = 100
    log = MessageLog()
    killed = attack(player, enemy, log)
    require(not killed, "durable enemy died from one normal attack")
    require(enemy.hp < enemy.max_hp, "attack did not reduce enemy HP")
    enemy.hp = 1
    require(attack(player, enemy, log) is True, "lethal attack was not reported as a kill")
    require(log.messages, "combat produced no message log entries")

    player = Player(position=Position(0, 0))
    player.hp = 1
    player.defense = 0
    enemy = Enemy(position=Position(1, 1), enemy_type=EntityType.GOBLIN)
    enemy.hp = enemy.max_hp = 100
    enemy.attack = 100
    require(resolve_combat(player, enemy, MessageLog()) is False, "player death reported the enemy as killed")
    require(not player.is_alive(), "enemy did not kill a one-HP player")


def check_items() -> None:
    from token_wyrm.items import use_item
    from token_wyrm.models import Item, ItemType, MessageLog, Player, Position

    player = Player(position=Position(0, 0))
    log = MessageLog()
    player.hp = 5
    potion = Item(position=Position(0, 0), item_type=ItemType.HEALTH_POTION)
    require(use_item(player, potion, log) is True, "health potion could not be used")
    require(player.hp > 5, "health potion did not heal")
    player.hp = player.max_hp
    use_item(player, potion, log)
    require(player.hp == player.max_hp, "healing exceeded max HP")

    weapon = Item(position=Position(0, 0), item_type=ItemType.WEAPON)
    base_attack = player.get_attack_power()
    require(player.equip_item(weapon) is True, "weapon could not be equipped")
    require(player.get_attack_power() > base_attack, "equipped weapon did not increase attack")

    armor = Item(position=Position(0, 0), item_type=ItemType.ARMOR)
    base_defense = player.get_defense()
    require(player.equip_item(armor) is True, "armor could not be equipped")
    require(player.get_defense() > base_defense, "equipped armor did not increase defense")


def check_save_load() -> None:
    from token_wyrm.engine import GameEngine
    from token_wyrm.models import Item, ItemType, Position

    engine = fresh_engine(7)
    engine.player.hp = 12
    engine.player.gold = 33
    engine.depth = 3
    engine.player.inventory.append(Item(position=Position(0, 0), item_type=ItemType.HEALTH_POTION))
    engine.player.position = Position(5, 5)
    engine.rng.random()
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "save.json"
        require(engine.save_game(str(path)) is True, "save_game failed")
        loaded = GameEngine(seed=999)
        require(loaded.load_game(str(path)) is True, "load_game failed")
        require(loaded.player.hp == 12, "loaded HP differs")
        require(loaded.player.gold == 33, "loaded gold differs")
        require(loaded.depth == 3, "loaded depth differs")
        require(loaded.player.position == engine.player.position, "loaded player position differs")
        require(len(loaded.player.inventory) == len(engine.player.inventory), "loaded inventory differs")
        require(len(loaded.game_map.entities) == len(engine.game_map.entities), "loaded entities differ")
        require(len(loaded.game_map.items) == len(engine.game_map.items), "loaded floor items differ")
        require(
            [[value(tile) for tile in row] for row in loaded.game_map.tiles]
            == [[value(tile) for tile in row] for row in engine.game_map.tiles],
            "loaded map differs",
        )
        require(loaded.rng.random() == engine.rng.random(), "RNG state was not restored")

        corrupt = Path(directory) / "corrupt.json"
        corrupt.write_text("{not json", encoding="utf-8")
        require(loaded.load_game(str(corrupt)) is False, "corrupt save did not fail cleanly")
        require(loaded.load_game(str(Path(directory) / "missing.json")) is False, "missing save did not fail cleanly")


def check_progression_boss_and_win() -> None:
    from token_wyrm.models import Position

    engine = fresh_engine(7)
    boss = None
    for _ in range(15):
        stairs = find_stairs(engine.game_map)
        require(stairs is not None, "a generated level has no stairs")
        engine.player.position = stairs
        old_depth = engine.depth
        engine.descend_stairs()
        require(engine.depth > old_depth, "descend_stairs did not increase depth")
        require(is_walkable(engine.game_map, engine.player.position), "player landed inside a wall")
        boss = next((entity for entity in engine.game_map.entities if is_boss(entity)), None)
        if boss is not None:
            break
    require(boss is not None, "no boss marked with is_boss or a boss/wyrm name appeared by depth 15")

    engine.player.hp = engine.player.max_hp = 999
    engine.player.attack = 999
    engine.player.defense = 999
    placed = False
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        position = Position(boss.position.x + dx, boss.position.y + dy)
        if not is_walkable(engine.game_map, position):
            continue
        require(engine.game_map.get_entity_at(position) is None, "boss has no free adjacent tile")
        engine.player.position = position
        direction = next(
            name
            for name, delta in {"UP": (0, -1), "DOWN": (0, 1), "LEFT": (-1, 0), "RIGHT": (1, 0)}.items()
            if delta == (-dx, -dy)
        )
        for _ in range(10):
            engine.move_player(direction)
            if not boss.is_alive():
                break
        placed = True
        break
    require(placed, "boss has no walkable adjacent tile")
    require(not boss.is_alive(), "buffed player could not defeat the boss")
    require(bool(getattr(engine, "win", False) or getattr(engine, "game_over", False)), "defeating the boss did not trigger a win")


def check_ui() -> None:
    import inspect

    from token_wyrm import render

    engine = fresh_engine(7)
    buffer = StringIO()
    with redirect_stdout(buffer):
        render.render_game(engine, use_color=False)
    output = buffer.getvalue()
    for marker in ("Depth", "HP", "Gold", "Messages", "Controls"):
        require(marker in output, f"UI output is missing {marker}")
    require("\x1b[" not in output, "no-color render still emitted ANSI escapes")
    source = inspect.getsource(render)
    require("Congratulations" in source or "win" in source.lower(), "no win screen found")
    require("Game Over" in source or "lose" in source.lower(), "no lose screen found")


def check_stdlib_only() -> None:
    stdlib = set(sys.stdlib_module_names)
    package = ROOT / "token_wyrm"
    for path in package.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules = [node.module]
            for module in modules:
                root = module.split(".", 1)[0]
                require(
                    root in stdlib or root == "token_wyrm",
                    f"{path.relative_to(ROOT)} imports non-stdlib module {module}",
                )


def check_readme() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()
    require(
        "setup" in readme or "install" in readme,
        "README is missing setup/installation instructions",
    )
    for marker in ("controls", "--seed", "save", "json", "pytest"):
        require(marker in readme, f"README is missing {marker}")


def main() -> int:
    run_check("cli_help", check_help)
    run_check("self_check", check_self_check)
    run_check("determinism", check_determinism)
    run_check("map_and_reachability", check_map_and_reachability)
    run_check("movement_and_collision", check_movement_and_collision)
    run_check("enemy_turns", check_enemy_turns)
    run_check("combat", check_combat)
    run_check("items", check_items)
    run_check("save_load", check_save_load)
    run_check("progression_boss_and_win", check_progression_boss_and_win)
    run_check("ui", check_ui)
    run_check("stdlib_only", check_stdlib_only)
    run_check("readme", check_readme)

    if FAILURES:
        print(f"\n{len(FAILURES)} checks failed")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        raise SystemExit(2)
