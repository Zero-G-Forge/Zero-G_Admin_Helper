# Zero-G Admin Helper — Engine Concepts and Explanations

Plain-English notes for a new coder. This file explains **why** ZAH is built the way it is. Exact names and signatures live in `Architecture_Documentation.md`. Update both files when a concept, fix, or design rule changes.

## Qt Widgets, Layouts, and Signals

### The window is a tree of boxes

A Qt program is a tree of **widgets** (on-screen pieces). A button, a label, a text box, and the main window are all widgets. A parent widget owns its children. When the parent is closed or deleted, the children go with it.

**Analogy:** the main window is a house. Each page is a room. Labels and buttons are furniture in that room. Moving out of a room (switching pages) can throw the furniture away, so work that must outlive the room cannot be left sitting on the furniture.

### Layouts place the furniture

A **layout** decides where children sit as the window is resized:

| Layout | Everyday meaning |
| --- | --- |
| `QVBoxLayout` | A vertical stack, top to bottom |
| `QHBoxLayout` | A horizontal row, left to right |
| `QGridLayout` | A table of rows and columns |
| margins and spacing | The padding between pieces |

ZAH almost never hard-codes pixel positions for a whole page. Cards and toolbars are packed into layouts so a resize still looks tidy.

### Signals and slots are doorbells

Qt objects talk through **signals** and **slots**:

- A **signal** is a named announcement, such as `clicked` or `toggled`.
- A **slot** is a method that runs when that announcement is heard.
- `button.clicked.connect(self._on_connect_clicked)` wires the doorbell to the handler.

**Analogy:** pressing a doorbell does not open the door by itself. It rings. A connected method is the person who hears the ring and decides what to do. The button does not need to know about the bridge, and the bridge does not need to know about the button.

This matters for threads: a background thread must not paint widgets directly. It **emits a signal**. Qt delivers that signal on the window thread, where it is safe to fill a table or change a label.

### Why a missing connection looks like a "broken" button

If a button is clicked and nothing happens, the usual causes are:

1. `connect` was never called.
2. The button is disabled (`setEnabled(False)`), often with the tooltip `Coming in a later step.`
3. The handler ran and failed inside a `try` / `except`, so the error is in the terminal log rather than on screen.

## The Page Loader

### Why each page is its own module

ZAH keeps each page in `features/<name>/<name>_page.py` with a `create_page()` function. The cockpit only knows a short **page key** such as `players`. Three lookup tables turn that key into a module, a nav label, and an icon.

**Analogy:** the nav column is a phone list. The key is a person's name. `PAGE_MODULES` is the phone book. The loader dials one number at a time. A wrong number must not bring down the whole switchboard.

### Why a failed page shows a card instead of crashing

`load_page` wraps the import and `create_page()` in `try` / `except`. On failure it returns an `ErrorCard` with a **RETRY** button. Retry reloads the module from disk, so a fix can be picked up without restarting ZAH.

This is deliberate. One broken page is an error card. The header, nav, and every other page keep working.

### Why ITEMS and BP EDITOR share one class

Both nav buttons open `LibraryPage`, on different starting tabs. That avoids two copies of the search box, the tile grid, and the detail card. The page key still has its own loader entry, so each button can have its own icon and nav highlight.

## Offscreen Testing

### What "offscreen" means

Qt needs a display system to build widgets. On a machine with no monitor session, or in a test script, the environment variable `QT_QPA_PLATFORM=offscreen` tells Qt to draw into memory instead of a visible window.

**Analogy:** it is like taking a photograph in a closed box. The camera still takes the picture. Nobody has to see the shutter move.

A typical check builds a `QApplication`, applies `ZAH_main.css` (so colours match the real program), resizes the widget, and calls `grab()` to save a screenshot.

### Why this is used

- It proves a page can be built without clicking through the whole boot and login path.
- It catches layout mistakes (clipped text, overlapping cards, missing styles) before they reach a live session.
- It does not need a running game server.

Harmless warnings sometimes appear in this mode, such as a platform plugin that cannot raise a window. They do not mean the screenshot is wrong.

### What offscreen tests must not do

They may read local files for layout checks, but they must not be treated as the long-term data source. Item configs, PDA files, and images that the program will actually edit come from files **downloaded from the server**, not from a local base-game copy.

## The ECF Format

### Blocks are labeled boxes inside labeled boxes

An Empyrion `.ecf` file is plain text. A block starts with `{` and a type name, and ends with `}`. Blocks may nest:

```text
{ +Item Id: 200, Name: MagnesiumOre, Ref: OreTemplate
  Mass: 6.51, type: float, display: true, formatter: Kilogram
  { Child 0
    Class: Ranged
  }
}
```

`parse_ecf_blocks` turns that text into Python dictionaries:

- `type` is the word after `{` (`Item`, `Child`, and others).
- `header` holds the `Id`, `Name`, and `Ref` from the opening line.
- `props` holds each body line as `{ "value": "6.51", "attrs": { "formatter": "Kilogram" } }`.
- `children` holds nested blocks (weapon modes are a common case).

**Analogy:** a recipe card (the item) can list ingredients (properties) and also include smaller cards for each cooking mode (children). A comment starting with `#` is a note in the margin and is ignored, unless the `#` sits inside quotes.

### Ref is inheritance

`Ref: OreTemplate` means "start from the template, then apply this block's own lines." `resolve_refs` walks that chain. The child's own keys win. The parser remembers `own_keys` so a stats window can mark inherited values as coming from the template.

If a template is missing, or a chain loops back on itself, the walk stops. The item still loads with whatever was already found (fail soft for display, without crashing the page).

### ShowUser hides templates

`ShowUser: No` marks templates and hidden items that players never see. `load_items` skips those rows so the library shows what an admin would actually hand out, not the behind-the-scenes templates.

The parser itself is **read-only**. It never writes a file.

## Localization.csv and PDA.csv Name Lookups

### Internal names versus English names

Game files use a stable internal name such as `AdrenalineShot`. The name a player reads is stored in a CSV file, usually under a `KEY` column and an `English` column.

`read_english_names(csv_path)` builds a dictionary from KEY to English text. The same helper serves both `Localization.csv` (items) and `PDA.csv` (chapter titles). If the file is missing, the lookup is empty and the internal name is shown instead.

**Analogy:** the internal name is a product code on a warehouse shelf. The CSV is the printed label on the front of the box. The program always stores the product code, and it puts the label on the tile when the label exists.

### Colour tags are stripped

PDA and item text often includes style tags such as `[c]`, `[b]`, a six-digit colour, or `[-]`. Those tags are removed before the name is shown or searched, so a chapter list is readable and a search for the visible words still matches.

## Syntax Highlighting

### Colour is a map over the text, not a second copy

`EcfHighlighter` and `PdaYamlHighlighter` are `QSyntaxHighlighter` subclasses. As each line is drawn, the highlighter paints ranges: braces, block types, keys, strings, numbers, keywords, and comments.

**Analogy:** it is a transparent colour overlay on a printed page. The letters underneath do not change. If the overlay is wrong, the file is still the same file.

The ECF code editor also draws line numbers and highlights the matching brace. That is why a missing `}` is easier to see before a later Validate step is wired.

The PDA editor reuses the same code editor widget, with the YAML highlighter passed in, so both pages share line numbers and caret behaviour.

## The Hex Tile Flow Grid

### Tiles are buttons that paint themselves

Each item is a `HexTile` (`QAbstractButton`). It paints a hex badge, initials or a short name, and a group colour (weapons, medical, and the other filters). Clicking a tile is the same idea as clicking a button: it emits a signal, and the detail card listens.

`make_hex_pixmap` can also draw a standalone hex for the detail card and the stats window. Until server images are wired, that drawn hex is the picture.

### Why the grid is a flow area, not a fixed table

`TileFlowArea` is a scroll area that **reflows** tiles when the window is resized or filters change. Tiles that do not match the current search or filter group are hidden; the rest pack left to right and wrap.

**Analogy:** it is a tray of magnets, not a spreadsheet. Widen the tray and more magnets sit on each row. A filter is a lid that covers some magnets without throwing them away.

Filters are a union: more than one group can be checked at once. With none checked, every item is shown. Search matches display name, internal name, and id.

## Fail-Closed Role Checks

### The default answer is no

A **fail-closed** check means "if anything is unclear, refuse." That is the opposite of fail-open ("if unsure, allow").

Examples in ZAH:

- An unknown or missing role has rank `-1`, below every real role.
- An unknown **needed** role also returns false, so a typo in `has_role_at_least` cannot open a door.
- The main window never opens unless login actually succeeded.
- A missing developer key does not let the offline developer login read the failed-login log.
- The login service checks permissions again, even if the Users page already did.

**Analogy:** a locked door that stays locked when the key is missing, unreadable, or the wrong shape. It does not swing open just because the paperwork is messy.

### Roles are a ladder, not four independent switches

`moderator` < `admin` < `owner` < `developer`. Asking "is this user at least admin?" is a height check on that ladder. An owner passes an admin check. A moderator does not.

The database will not store `developer`. That keeps the top role on the offline owner login for this computer (and on the developer key for a few service routes), instead of as a row anyone could add in the Users dialog.

## Why Download-Edit-Upload Beats Live Editing

### Two ways to change a server file

| Mode | Everyday meaning | Risk |
| --- | --- | --- |
| Download, edit, upload | Make a local copy, edit it, then send it back on purpose | A typo stays on this computer until an upload is approved |
| Live mode | The editor is pointed at the real file on the server | A typo can affect the live game as soon as it is saved |

**Analogy:** download-edit-upload is taking a document to a desk, marking it up, and walking it back to the filing cabinet. Live mode is writing on the official copy while people are still using it.

### Why the default is the desk copy

- The operator can Validate, read a changes preview, and keep a backup before anything reaches the server.
- The app can be used while the server is busy, and the local copy is still there if the connection drops.
- Uploading is a clear, approved step, which matches the project rule that server changes need an explicit go-ahead.

### Why live mode still exists, with brakes

Some tasks need to see the file that is on the server right now. LIVE MODE is that path, but it is built to be hard to use by accident:

- It always starts **off**, and that choice is never saved.
- Only developers and owners get it by default. An owner can later grant a named admin or moderator the Live file editing permission.
- A live save must pass three confirmations, including a check for online players and typing the file name.
- The old file is backed up before the new one is written.
- Until the bridge **write** commands and the database column exist, the switch stays disabled. The read-only file commands (`files:`) exist now, but reading is not writing, so they do not unlock LIVE MODE.

## The Bridge and Disabled Server-Changing Buttons

### The bridge is a narrow letterbox

ZeroGBridge is a mod inside the game process. ZAH does not reach into the server's disks by itself. It sends one-line commands through a logged-in TCP connection, and it reads one-line JSON replies.

**Analogy:** the game is a house. The bridge is a letterbox with a lock. ZAH can only post letters (commands) that the letterbox already knows how to sort. A new kind of letter, such as "please send these files," has to be added to the letterbox first, and that change has to be approved. That letter now exists: the read-only `files:` commands. See the next big section.

Because the letterbox sits in the game, game reads and writes run on the **game thread**. The network thread only accepts the line and hands the work over. That prevents the game and the network from grabbing the same data at the same time.

### Why so many buttons are disabled

Many pages are laid out and styled, but the action buttons (kick, ban, upload, wipe, live save, and others) stay disabled with `Coming in a later step.`

This is intentional:

- A finished-looking button is easy to click by habit. A disabled button cannot send a command that was never meant to go out yet.
- Several of those actions would change the live server. The project rule is that those changes wait for an explicit request.
- The layout can be reviewed and adjusted without connecting the dangerous side first.

Connect on the ZeroGBridge page is the safe exception: it logs in to the active server's bridge and does not send a game command by itself. Portal Reload and Rollback stay developer-only, because they swap the running bridge core.

`save` and `backup` are also honest about their limits: the game has no save-only console command, and backups are not a bridge command. The catalog returns `not_available` rather than pretending those words do something.

## Downloading Server Files Through the Bridge

### What the download does, in one picture

**Analogy:** a librarian who guards two named shelves. ZAH hands the librarian a slip with a shelf name and a book title. The librarian checks the slip, fetches a **photocopy**, and passes it through the window. The librarian never hands over the original and never lets anyone walk into the stacks.

- The two shelves are `scenario` (the scenario that is being played) and `save` (the current save game).
- The librarian is the `files:` commands inside ZeroGBridge. ZAH is the person at the window.
- The photocopy lands in `data/server_files/<scenario>/` on this PC, laid out like the server's folders.

### Why the bridge only reads

The window has glass in it. The bridge opens every file for **reading only** and in a mode that lets the game keep using the file at the same time. There is no command that writes, renames, or deletes. Putting changed files back on the server is a different, later step that needs its own approval.

(Update, core 1.6.2: that later step now exists as a separate command, `files:put`. The read commands above still only read. See **Writing Files Back Through the Bridge** below.)

### Why the names on the slip are checked so hard

A slip that says `../../somewhere/else` is an attempt to wander out of the shelf. So the bridge checks the slip in layers, like a security desk:

1. The text of the name: no `..`, no full paths from the top of the disk, no drive letters, no strange characters, no names Windows treats as devices.
2. The kind of file: only configuration, PDA, and picture types (`.ecf`, `.yaml`, `.yml`, `.csv`, `.jpg`, `.png`). A database or a password file is never on the menu.
3. The room: only named folders inside each shelf.
4. The real address: the bridge turns the name into a full address and proves it is still inside the shelf.
5. Shortcuts: a folder or file that is really a pointer to somewhere else (a symlink) is refused.

Each layer is cheap, and any one of them stops the common tricks. Together, a mistake in one layer is caught by the next. ZAH does its own check too: even a hostile or buggy server cannot make ZAH write outside `data/server_files/`.

### Why file content travels as base64 text

The bridge talks in single lines of text. A picture is bytes, and bytes can contain a line break by accident, which would cut the line in half. **Base64** is a way to write any bytes using only safe letters and digits.

**Analogy:** sending a statue by post. You cannot put a statue in a letter, but you can flat-pack it and number the pieces. The receiver follows the numbers and puts the statue back together. Base64 text is about one third bigger than the original, which is the price of the flat-pack.

### Why big files arrive in pieces, and small ones in batches

The letterbox slot only takes so much at once. One reply carries at most about 192 KB of file data.

- A small file shares the reply with others, like several letters in one delivery.
- A file bigger than one reply comes in numbered pieces. ZAH asks for the next piece by saying where the last one ended (`offset`).
- Whatever does not fit comes back marked `deferred`, which means "ask me again."

At the end, ZAH checks that the pieces add up to the size the server announced. If a file changes on the server halfway through, ZAH starts that file over instead of gluing two versions together.

### Why a download writes a `.part` file first

**Analogy:** a cook plates the meal on a prep tray, and only carries it to the table when it is finished. ZAH writes into `<name>.part`, and only when every byte has arrived and the size matches does it swap the finished file into place (`os.replace`, one step). If ZAH or the PC stops halfway, the real file is never half written.

### Why there is a manifest

`_manifest.json` is a packing slip: for each file it notes the size and modified time that were pulled. The next download compares the server's list with the slip and fetches only what is new or changed. A first run may take a few minutes because of the half-second pause between commands. Later runs are short.

Old local files are never deleted, even if the server no longer has them. Deleting is a decision for a person, not for a sync button.

### Why the download uses its own connection

The dashboard's connection is a radio that keeps broadcasting status lines. A download wants exact answers to exact questions. Sharing one line would mean sorting reports from answers. So the download opens a **second, short connection**, logs in the same way, and hangs up when done. The password is only ever written to that socket. It is never printed, logged, or put in an error message.

### Why an old bridge fails closed

The server will not have the `files:` commands until the new core is installed. An old bridge answers an unknown command with a generic "Acknowledged." ZAH sees that the answer is not a `FILES` answer, stops, writes nothing, and says: `This server's ZeroGBridge does not have the file commands yet. Ask the owner to update the bridge.` A wrong guess here could have meant treating "Acknowledged" as success and showing an empty download.

### Why the bridge remembers the two folders instead of asking each time

Asking the game for a folder is a game-state read, and game-state reads run on the **game thread**. The network thread must not do that. So the bridge asks the game for the scenario and save folders on the game thread (at most every 30 seconds), writes them in a notebook, and the network side only reads the notebook. If the game has not answered yet, the bridge reports `root_unavailable` and ZAH says to try again in a minute.

### Why the new core can be installed without a restart

ZeroGBridge is two DLLs: a small loader that never changes, and a **core** that holds all the commands. The `files:` commands live in the core, so Ray installs them with the hot reload that already exists (drop the new core DLL into the `Updates` folder, then send `hot:reload`). If the new core fails its start-up check, the old one keeps running. The loader, the port, and the connected ZAH sessions stay up.

### How it was tested without touching a server

- A C# check program compiles the real `ServerFiles.cs` and runs it against a temporary folder full of test files, including attack paths and symlinks.
- The same program can act as a stand-in bridge. ZAH's Python tests download from it, change a file, and download again to prove only the changed file comes down.
- A second stand-in plays an "old bridge" to prove the fail-closed message.
- The Settings page is created off-screen to check the button states: off with no connection, on when connected, off while downloading.

## Reading the Downloaded Copy Instead of the Game Folder

### One source of truth

Before, the Library could read any folder it was pointed at, including a game install on this PC. That copy can be older or different from what the server runs. Now every page reads only the photocopy the download made, so what ZAH shows is what the server has.

### Why the save copy wins

When a game is first started, the scenario's files are copied into the save. After that the server reads the save's copy. So when the same file exists in both places, ZAH shows the save's copy.

### Why the scenario name is not written into the code

The bridge reports the scenario name, and the download names the local folder after it. ZAH looks the folder up from Settings instead of assuming a name, so a switch from "Default Multiplayer" to "Ascension-Reborn" needs no code change.

### Pictures: one look at the folder, then a lookup table

The Library may hold over a thousand items. Asking the disk "is there a picture for this one?" a thousand times is slow, so ZAH lists the Images folder once and builds a table from lower-case item name to picture file. Each item then just looks itself up. The picture is cut to the hex shape with a **clip path**, which works like a stencil: paint only lands inside the shape.

## Validating, Comparing, and Saving Edits

### The downloaded copy stays untouched

A local save goes to a separate edited copy, so ZAH can always compare your work with what was downloaded.

### Backups come before replacement

Each save first copies the previous version into `_backups` with a date and time in the name. Nothing is deleted.

### A diff is a list of changes

Changes Preview marks removed lines with `-` and added lines with `+`, so you only read what changed.

## Writing Files Back Through the Bridge

### The mail slot now has a return tray

Core 1.6.2 adds two commands that write: `files:put` puts one edited file back, and `coreupload:put` puts a new bridge core into the `Updates/` folder. Both live in the core, so installing them is a hot reload, never a restart.

### Why the old file is copied before anything else happens

Think of replacing a page in a binder. First the old page goes into a labelled folder (`Backups/`, stamped with the date and time). Only then does the new page go in. If the new page turns out wrong, the old one is still there. The bridge never empties that folder.

### Why the file arrives in pieces into a waiting room first

A big file cannot fit in one message, so it is sent in pieces of up to 128 KB. The pieces collect in the bridge's own `Uploads/` waiting room, not next to the game's files. Only when every piece has arrived, and the fingerprint matches, is the file moved into place.

### Fingerprints: sha256

A sha256 is a 64-character fingerprint of a file's exact bytes. Change one letter and the fingerprint changes completely. ZAH sends two fingerprints:

- **sha256** of the new file. If what arrived has a different fingerprint, a piece was lost or damaged, and nothing is replaced.
- **base_sha256** of the copy ZAH downloaded. If the file on the server no longer has that fingerprint, someone else changed it in the meantime. Writing over it would silently throw their change away, so the bridge refuses and says "download it again first".

### Why the swap is one step

The new file is first written right next to the old one under a temporary name, then swapped in with a single operating-system call (`File.Replace`). The game either sees the whole old file or the whole new file, never half of each.

### Why it is called coreupload and not hot:upload

The loader, the small part that never changes without a restart, answers every line that starts with `hot:` itself. A new `hot:` word would mean changing the loader, and that means restarting the server. So the upload lives in the core under its own word, `coreupload:`, and writes into the same `Updates/` folder that `hot:reload` already reads from. The reload step is unchanged: the loader still checks the new core and keeps the old one if the check fails.

### The very first time still needs hands

A command can only be used once the core that contains it is running. So core 1.6.2 itself has to be dropped into `Updates/` by hand one last time. After that reload, later cores can travel through `coreupload:`.

### The off switch

`"FileWritesEnabled": false` in `ZeroGBridge.json` turns both write commands off. The bridge reads the setting on every call, so flipping it takes effect at once.

## Uploading an Edit From ZAH

### Three questions before anything leaves the PC

A wrong config file can break the game for everyone online, so ZAH asks three different questions, each one a chance to stop:

1. **What changes?** The same diff as the Changes Preview. It is easy to see an accidental deletion here.
2. **Who is playing?** ZAH asks the bridge for the player list right then (a read-only question). If anyone is online the warning names them. If the list cannot be read, ZAH stops, because "unknown" is not the same as "nobody".
3. **Which file?** Typing the file name by hand makes sure the right file is going up, and stops a click made out of habit.

### The role gate, and why "missing" means "no"

Developers and owners may always upload. An admin or moderator may only when the owner ticked **Live file editing** for them, which is a column in the users table. ZAH asks the login service, and the service answers True only when the column exists and says TRUE. If the column was never added, the question cannot be answered, and the safe answer is no. This is called failing closed: when in doubt, the door stays shut.

### What happens after the upload

The server now has the new file, so ZAH makes its downloaded copy match (after backing up the old copy). The diff becomes empty again, and the next upload is checked against the new fingerprint. If somebody else changed the file on the server first, the bridge refuses, nothing is replaced, and ZAH says to download again.

### LIVE MODE

LIVE MODE is a switch, not a setting: ZAH forgets it on every start and every sign-in. While it is on, opening a file asks the server for its current copy first, and SAVE goes straight on into the three questions. With it off, editing is purely local until UPLOAD is pressed.

### Uploading a new bridge core from the portal

The portal's Browse button can now send a new `ZeroGBridge.Core.dll` (and its `.pdb`) into the server's `Updates/` folder. That alone does not change the running bridge. The usual Reload now confirmation appears next, and only that loads the new core. Developer only.

### How the uploads were tested without touching the server

The tests start the bridge's real C# file code as a small local stand-in server (`ServerFilesTest serve`), with `ZGB_TEST_MODDIR` pointing at a throwaway folder for its `Uploads/`, `Backups/` and `Updates/`. ZAH then uploads to that stand-in exactly as it would to the real one. The tests check the happy path, a refused stale upload, every "No" answer, the role gate, LIVE MODE, and a core upload. The live server was never written to.

## The Safety Flow

### Four brakes before a server change

A kick, a ban or a wipe cannot be undone with Ctrl+Z, so every such button goes through the same four brakes:

1. **Who are you?** The role ladder decides. An action that is not in the table is refused, so a new button can never be "open by accident".
2. **What exactly?** The real command line is shown before anything else. What is shown is what is sent.
3. **Do you mean it?** Typing `CONFIRM` takes a moment of thought that a reflex click does not.
4. **Last chance.** 15 seconds to change one's mind, with CANCEL.

After the send, one line goes into the audit log, like a ship's logbook: who did what, when, on which server, and what the server answered. Cancelled actions are logged too.

### Read-only views need no brakes

Lists, stats and inventories only look, so they load in the background without asking. Their buttons still check the role before anything that changes the server.

### Why SAVE and BACKUP stay off on the Dashboard

The game saves by itself. The only command that forces a save is `saveandexit`, which also shuts the server down, and copying a save folder while the game writes to it can catch half-written files. Both need a stopped server, which is a restart, so the buttons stay off.

### Why GOD MODE stays off

The game's `godmode` command toggles the player who types it in their own console. The server console has no player to toggle, so there is no way to send it from ZAH.

## Chat History Through the Bridge

### The game tells, it is not asked

The game has no "give me the last messages" request. Instead it rings a doorbell (`ChatMessageSent`) each time someone talks. Core 1.6.3 listens to that doorbell and writes each line into a small notebook that holds the newest 500 lines. ZAH reads the notebook with `chat:recent`.

### Why ZAH asks for "since"

Every line gets a number (`seq`). ZAH remembers the highest number it has seen and asks only for newer lines, so each poll is small. After a bridge reload the numbers start at 1 again; ZAH sees the smaller number and starts over.

### Why the notebook forgets on reload

It is kept in memory only, so nothing is written to the server's disk. Chat from before the reload is gone; ZAH still has what it already read.

### Watch words stay on the PC

Watch words are a private list on the admin's PC. A match only shows up in RECENT HITS; nothing is sent until WARN goes through the Safety Flow.

## Factions Are Read-Only

### What ZAH can see

The faction list, each faction's members (from the player list), and which factions are allied. All three are reads, so the page needs no Safety Flow.

### Why SET RELATION and RENAME stay off

Changing relations is something the game only lets a player do from their own console, and neither the mod API nor the server console can rename a faction. The bridge could only pretend, so the buttons stay off and say why.

## Structures

### The list only shows what is awake

The bridge reports structures from playfields that are loaded right now (`gents`). A base on an empty planet nobody visits may be missing until that playfield loads. The count bar counts what was reported, not every structure in the save.

### Why TELEPORT TO lifts the player

The bridge gives the structure's centre point. Landing exactly there could put the player inside a wall, so ZAH aims 15 m above it.

### Why SET FACTION stays off

The mod API can rename or destroy a structure, but it has no request to hand one to another faction. The button stays off and says why.

## Playfields

### Loaded versus known

The server knows every playfield in the scenario (well over a thousand here), but only a few run at a time. ZAH counts all of them and makes cards only for the loaded ones, because only those can be stopped or restarted.

### Why RESTART waits 20 seconds

Stopping a playfield shuts down its own small server process. Loading it again before that process has gone could fail or be ignored, so ZAH waits 20 seconds between the two steps.

### Why WIPE does not happen at once

The game's `wipe` only marks what to clear. The clearing happens the next time the whole server starts. ZAH never restarts the server, so the wipe waits for Ray's next planned restart.

### Why the old pfstats shorthand is not used

Like `msg:`, the plain `pfstats:` shorthand only answers with an empty box. ZAH asks the real Eleon request `Request_Playfield_Stats` instead.

## Alerts

### Where alerts come from

ZAH has no separate anti-cheat feed. It builds the queue from two things it can already read: the game's own cheat flags on each player (CRITICAL), and chat lines that contain a watch word (WARNING).

### Why ACK stays on the PC

Acknowledging an alert is a note for the admin, not a change to the game. It only hides the row in this ZAH window until ZAH closes.

### Why BEFORE and DELTA are empty

The game reports how a player looks now, not how they looked a minute ago. Showing a change would need ZAH to keep its own history, so those columns stay `--` for now.

## Why Backups Stay Locked

A save folder is many files that the game keeps writing while it runs. Copying it in the middle can catch some files old and some new, and putting an old copy back while the game runs would be overwritten or break the save. Both need the server stopped first, and stopping it is a restart, which ZAH does not do. So the BACKUPS page explains this instead of offering buttons that cannot work.

## Staying Connected

### Why a drop is retried, but a disconnect is not

If the line goes dead on its own (the server's network hiccups, the bridge reloads), the admin still wants to be connected, so ZAH tries again: first after 5 seconds, then waiting longer each time up to once a minute. Pressing DISCONNECT, switching servers or closing ZAH is a clear "stop", so those are never undone.

### Why ZAH asks "plys" every 30 seconds

The connection only notices it is dead when it tries to send something. A small read-only question every 30 seconds is enough to find out, without changing anything on the server.

### Watching several servers at once

Each saved server is asked the same three read-only questions on its own short connection. Nothing is kept open, so a slow or dead server cannot block the main one. A message to all servers passes the Safety Flow once, then goes to each server in turn, and each one gets its own line in the audit log.

## Giving Items and Building Templates

### Why "pending edits" became GIVE ITEM

The first drawing had a queue of pending edits that would be sent later. ZAH has no such queue: every server change already gets its own preview and CONFIRM in the Safety Flow, so a second waiting room would only add a step. The button now gives the item straight through the Safety Flow.

### Templates live on the PC

ADD TO TEMPLATE only writes to a small file on the admin's PC. Nothing reaches the server until a template button on the Players page is used, and that goes through the Safety Flow too.

## Stopping a Download Politely

CANCEL DOWNLOAD does not pull the plug in the middle of a file. It raises a flag, and the download thread looks at that flag between two requests. Files that already arrived stay, the half-finished `.part` file is thrown away, and LAST PULLED is not changed, because the copy is not complete.

## Background Threads for Network Calls

### The window thread must stay free

The thread that draws the window is also the thread that handles clicks. If that thread waits on a network call, the window freezes: the clock stops, buttons do not depress, and the program looks "stuck."

**Analogy:** the cashier should not leave the till to walk to the warehouse. Someone else walks to the warehouse and brings the box back. The cashier stays at the counter.

ZAH uses `QThread` helpers for that walk:

- `CommandPipe` keeps the bridge socket, logs in, and sends queued commands about half a second apart.
- `ServerFileDownloadWorker` copies the server's files for the Settings download button.
- `FailedLoginFetcher` loads the failed-login table.
- `UserTaskRunner` lists, saves, and deletes login users.
- The portal uses a similar "run this call in the background" helper.

Each helper emits a signal when the answer arrives. The page fills widgets in the connected slot, on the window thread.

### Why the thread belongs to the app, not the page

Switching nav pages **deletes** the old page widget. If a `QThread` is a child of that page, Qt deletes the thread too. Deleting a thread that is still running crashes the program with `QThread: Destroyed while thread is still running`.

The fix is to parent those short network threads to the **application** (`QCoreApplication.instance()`), which lives until ZAH closes, and to call `deleteLater` when the thread emits `finished`. `CommandPipe` is parented to `MainCockpit` for the same reason: the cockpit outlives any one page.

`ServerFileDownloadWorker` has a variation of the same rule. It can run for minutes, and the user may click to another page meanwhile. The Settings page keeps every running download in a module-level list (`RUNNING_DOWNLOADS`), so the thread is never thrown away mid-run, and each thread removes itself from the list when it finishes. The page's own signals disconnect by themselves when the page is deleted, so a finished download that nobody is watching ends quietly.

`processEvents()` is used only in small spots (for example, to let a "Checking login" label redraw before a short wait). It is not a substitute for a real background thread on longer calls.

## Notable Past Fixes

These are lessons already paid for in git history. Each one is written as "what broke" and "why the fix works."

### A changed file was not noticed for a few seconds

**What broke:** the first version of `files:list` saved its folder scan for 10 seconds so paging would be quick. A file changed and re-pulled within those 10 seconds still looked unchanged.

**Why the fix works:** the first page of a list (`offset` 0) now always scans again. Later pages reuse that same scan for up to a minute, so the pages of one download agree with each other, but a new download always starts from a fresh look at the folders.

### Paths came from the wrong folder

**What broke:** assets and `data/` were resolved from the current working directory. Launching ZAH from another folder made it miss its stylesheet, icon, and settings.

**Why the fix works:** `features/paths.py` anchors every path to the folder that holds `ZAH.py`. The working directory can change; the app root does not.

### A mid-load page switch crashed ZAH

**What broke:** a background fetch was parented to the page. Changing pages destroyed the thread while it was still running.

**Why the fix works:** fetch threads are owned by the application, then freed with `deleteLater` after `finished`. The page can go away; the thread is allowed to finish first. See commit `fa1809b`.

### The signed-in role was not a real ladder

**What broke:** some windows assumed a fixed label, or compared role names by hand. Offline login and portal tools needed a single rule.

**Why the fix works:** `ROLE_ORDER` and `has_role_at_least` sit in one module. The offline owner login signs in as developer. The portal is admin and up. Reload and Rollback stay developer only. Unknown roles fail closed.

### Users from one server must not see another server's accounts

**What broke:** a shared user list could show every login. An admin needed a tighter scope.

**Why the fix works:** owners and admins see only their own server's users. Admins may manage moderators only. The service enforces the same rule, so a crafted client request still fails. Roles are shown capitalized; the stored name stays lower-case.

### Session tokens were easy to drop between windows

**What broke:** a successful online login did not always hand the token to `MainCockpit`, so owner-only calls (failed logins, user management) had nothing to send.

**Why the fix works:** the loader, the backup login path, and `set_signed_in_user` all carry the token through. Logout ends the token at the service and deletes the local session file.

### "Keep me logged in" needed two different notes

**What broke:** the developer login has no online token, and an online token must not be stored as if it were a password.

**Why the fix works:** online remember stores a session token and checks `/session` at the next start. The developer path stores a signed remember note on this computer only, and logout clears it. Both paths fail closed if the note is missing, expired, or not valid.

### Lockouts looked like ordinary wrong passwords

**What broke:** a 429 from the service was easy to show as a generic failure, which invited more tries.

**Why the fix works:** ZAH recognizes the lockout and shows `Too many tries, wait 15 minutes`. A dead service shows a different message and does not count as a wrong try.

### Header widgets could be missing during a refresh

**What broke:** a status refresh could run before header labels existed, or after a failed setup, leading to `None` errors.

**Why the fix works:** those updates check that the widget exists before they write to it. A partial setup must not crash the shell.

### The bridge catalog had to tell the truth about save and restart

**What broke:** it is tempting to map the word `save` to a console command the game does not have, or to restart the host from a command that only stops the process.

**Why the fix works:** `save` and `backup` return `not_available` with a clear message. `restart:<minutes>` warns players, then sends `saveandexit` with a value from 0 to 15. Starting the host again remains a panel job outside the bridge. The `cmds` catalog documents this so ZAH does not guess.

### Some old shorthand commands only pretended

**What broke:** `msg:`, `msgfaction:`, `broadcast:`, `destroystruct:`, `touchstruct:` and the credit commands in the core dispatcher only write a log line and answer "Sent" or "Success". Nothing reaches the game. The first wiring of MESSAGE, ANNOUNCE, chat SEND and WARN used them, so ZAH would have reported success for messages nobody saw.

**Why the fix works:** ZAH now sends the real Eleon requests (`api:Request_InGameMessage_SinglePlayer`, `_Faction`, `_AllPlayers`, `api:Request_Entity_Destroy`). Those wait for the game's own `Event_Ok`, so "ok" means the game really took it. The stubs are marked as stubs in the command table and are not used.

### Faction rows were easy to mis-count

**What broke:** earlier bridge versions could sort faction rows in a way that mixed NPC or dropped rows with player factions.

**Why the fix works:** later cores classify a row by origin first, refresh the faction cache on the game thread, and treat the reserved faction id consistently, so the list ZAH will eventually show is the player-facing one.

### Auto-connect must not surprise anyone

**What broke:** a program that dials the server the moment it opens can touch a live game before the operator is ready.

**Why the fix works:** `bridge_auto_connect` defaults to false and is stored only when the Settings checkbox is changed on purpose. The first start never connects by itself.
