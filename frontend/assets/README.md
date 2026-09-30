# Pixel art

Everything in this folder comes from **Ninja Adventure - Asset Pack** by
pixel-boy, <https://pixel-boy.itch.io/ninja-adventure-asset-pack>, released
under **CC0** (public domain). Attribution is not required; it is given here
because it is deserved.

| here | from the pack |
| --- | --- |
| `chars/<name>/face.png` | `Actor/Characters/<Name>/Faceset.png` (38×38 portrait) |
| `chars/<name>/idle.png` | `Actor/Characters/<Name>/SeparateAnim/Idle.png` (4 directions: down, up, left, right) |
| `chars/<name>/walk.png` | `Actor/Characters/<Name>/SeparateAnim/Walk.png` (4 directions × 4 frames) |
| `hud/bubble.png` | `HUD/NinePathRect/DialogueBubble.png` (nine-slice, 6px border) |
| `hud/facebox.png`, `dialog.png`, `choice.png`, `yes.png`, `no.png` | `HUD/Dialog/` |
| `hud/think.png` | `HUD/Dialog/DialogInfo.png` ("..." emote, 5 frames) |
| `hud/heart.png` | `HUD/Heart.png` (full → empty, 5 frames) |
| `food/*.png` | `Items/Food/` |
| `room/cat.png` | `Actor/Animals/Cat/SpriteSheet.png` |
| `room/floor.png` | `Backgrounds/Tilesets/Interior/TilesetInteriorFloor.png`, tile at (96, 208) |
| `room/wall.png` | same sheet, tile at (16, 16) |
| `room/rug.png` | same sheet, 64×64 at (240, 0) |
| `room/plant.png`, `bookshelf.png`, `shelf.png`, `dresser.png`, `table.png` | `Backgrounds/Tilesets/TilesetElement.png`, 16px grid crops at (0,112), (128,112), (48,112), (16,112), and the table 48×16 at (32,160) |

## Flower logo (`brand/`)

`brand/flower-mark.png` is Flower's logo, resized from <https://flower.ai>;
`brand/flower-pixel.png` is the logo-with-stem from the `adap/flower`
repository, redrawn at 19×32 on the pixel grid to sit on the table. They belong to Flower
Labs and are **not** CC0; they are shown only to say the project is built on
Flower, alongside the team's own "aius" badge.

## Characters

A profile picks its character with `"character": "<name>"` (a folder under
`chars/`); anyone without one is given a free character chosen from their name.
