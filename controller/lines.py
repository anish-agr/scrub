"""Every line Scrub says. Only the controller writes these (CONTRACTS: Event.say). Keep them short."""

STOPPED = "Stopped."
UNKNOWN = "Which instrument?"  # no tray item to hint with; see unknown()
NOT_IN_SETTING = "That's not on this tray."
NOTHING_OUT = "Nothing's out."
BUSY = "One moment, I've got three waiting."
ERROR = "Something went wrong. Holding."
HAND_LOST = "Lost your hand. Holding."
HAND_CLOSED = "Your hand closed. Holding."
PATH_BLOCKED = "Something's in the way. Holding."
OUT_OF_REACH = "That's out of my reach."
SHOW_HAND = "Hand open, please."
RESET = "Reset. Ready."
NEEDS_RESET = "I'm stopped. Reset me first."
SAY_GOT_IT = "Say got it when you have it."
SET_DOWN_FAILED = "Couldn't set it down. Holding."
CHOICE_EXPIRED = "That choice expired. Ask for the instrument again."
CHOICE_UNVERIFIED = "I can't verify that instrument's position. I won't move."
CHOICE_TIMEOUT = "No choice received. I won't move."


def with_you(name): return f"The {name} {'are' if _plural(name) else 'is'} with you."
def quantity(name, n): return f"{n} {name if _plural(name) or name.endswith('s') else name + 's'}"
def which_one(name, labels):
    return (f"Which {name}: " + " or ".join(labels) + "?" if labels
            else f"I can't distinguish the {name}. Check the tray and ask again.")
def other_instance(name): return f"The {name} is with you. Would you like the other one on the tray?"


def cap(s): return s[:1].upper() + s[1:]


def coming(name): return f"{cap(name)} coming."
def coming_sharp(name): return f"{cap(name)} to the safe spot."
def queued(name): return f"{cap(name)} next."
def _plural(name): return name.lower().endswith(("scissors", "pliers", "cutters", "forceps"))
def _here(name): return "Here are" if _plural(name) else "Here's"
def handed(name): return f"{_here(name)} the {name}. Ready to grab."  # said as the arm reaches the hand
def retry(name): return f"Missed the {name}, trying again."
def couldnt_pick(name): return f"I couldn't pick the {name}."
def not_on_tray(name): return f"I don't see the {name} on the tray."
def sharp_down(name): return f"{cap(name)} down, on the safe spot. Careful, it's sharp."  # the "Scalpel down" call-out
def no_pull(name): return f"Setting the {name} down."
def set_down(name): return f"Setting the {name} down."
def no_hand(name): return f"No hand. {cap(name)} {'are' if _plural(name) else 'is'} at the safe spot."
def path_blocked_down(name): return f"Something's in the way. {cap(name)} {'are' if _plural(name) else 'is'} at the safe spot."
def returned(name): return f"{cap(name)} back in {'their' if _plural(name) else 'its'} slot."
def couldnt_return(name): return f"I couldn't put the {name} back."
def auto_return(name): return f"Returning the {name}."
def no_taught(name): return f"I have no taught skill for the {name}."  # --skills taught and none recorded


# Sharps (any item with sharp: true) only ever go to the taught safe zone.
HAND_BACK = "Hand back, I'm holding a sharp."   # a hand inside the keep-out while a sharp is held
CLEAR_ZONE = "Clear the safe spot."             # the overhead camera sees something in the safe zone
def zone_not_taught(name): return f"The safe spot isn't taught. I won't pick the {name}."
def zone_too_close(name): return f"The safe spot is too close to the handoff. I won't pick the {name}."
def method_unavailable(method): return f"The {method} pick isn't ready for that one."  # a trial forced a method
def zone_blocked_back(name): return f"The safe spot stayed blocked. {cap(name)} back in {'their' if _plural(name) else 'its'} slot."


def _a(word): return ("an " if word[:1] in "aeiou" else "a ") + word


def unknown(name, word): return f"Which instrument? You can say: call the {name} {_a(word)}."  # teaching hint (X6)
def alias_added(word, name): return f"Got it: {word} means the {name}."
def alias_taken(word, name): return f"{cap(word)} already means the {name}."
BAD_ALIAS = "I didn't catch the word. Say: call the hemostat a crile."
HINT_WORDS = ("crile", "grabber", "nipper")  # teaching-hint examples: the first one this tray doesn't have yet


def count(names):
    if not names:
        return "Everything's on the tray."
    return "Out: " + ", ".join(names) + "."


def _the(names): return " and ".join(f"the {n}" for n in names)
def camera_gone(names): return f"Camera also sees {_the(names)} gone."
def camera_back(names): return f"Camera sees {_the(names)} back."


# Tray check (X3): GET /tray_check. Names come from the current setting.
CANT_CHECK_TRAY = "I can't check the tray right now."
TRAY_NOT_READY = "The tray isn't ready."


def _poss(name): return name + ("'" if name.endswith("s") else "'s")


def tray_ready(names): return "Tray's ready: " + ", ".join(names) + "."
def tray_missing(names): return f"Missing {_the(names)}."
def tray_wrong_slot(name, slot_name): return f"The {name} is in the {_poss(slot_name)} slot."
def tray_wrong_place(name): return f"The {name} is in the wrong slot."
def tray_extra(names): return f"Extra on the tray: {', '.join(names)}."
def tray_other_setting(seen, current): return f"The camera is checking the {seen} tray, not the {current} tray."


# The robot model (Perceptron) refused or is down (L2). Codes from arm/perceptron.py's APIError.
API_KEY_REFUSED = "The robot model key was refused. Check the team key."
API_BUSY = "The robot model is busy with another session. Try again in a moment."
API_DOWN = "The robot model is down right now."
API_UNREACHABLE = "I can't reach the robot model right now."
API_REFUSED = "The robot model refused the request."


def api_error(code):
    if code is None:
        return API_UNREACHABLE  # transport failed, or no key in .env
    if code in (401, 403):
        return API_KEY_REFUSED
    if code in (409, 429):
        return API_BUSY
    return API_DOWN if code >= 500 else API_REFUSED


def api_failed(code): return api_error(code) + " Holding."  # a skill failed on it: the arm waits for a reset


# Judge mode (L3): a judge may only ask for an instrument, the count, got it or stop.
JUDGE_ONLY = "In judge mode I can hand you an instrument, read the count, or stop."


# Reading (OCR): read_sheet, read_tray, read_pack. Numbers and names come from vision's read and the setting.
READING = {"read_sheet": "Reading the count sheet.", "read_tray": "Reading the tray tag.",
           "read_pack": "Reading the pack label."}
STILL_READING = "Still reading."
CANT_READ_SHEET = "I can't read the count sheet."
CANT_READ_TAG = "I can't read the tray tag."
CANT_READ_PACK = "I can't read the pack label."
SHEET_MATCHES = "Sheet matches my count."
SHEET_NO_COUNTS = "No counts are written on the sheet yet."


def _count_of(n, name):
    """"1 hemostat", "0 hemostats", "2 mayo scissors"."""
    return f"{n} {name if n == 1 or name.endswith('s') else name + 's'}"


def sheet_closing(name, sheet, scrub): return f"Sheet says {_count_of(sheet, name)} back, I count {scrub}."
def sheet_initial(name, initial, expected): return f"Sheet says {_count_of(initial, name)} at the start, {expected} expected."
def sheet_other_tray(seen, current): return f"This sheet is for the {seen} tray, not the {current} tray."
def sheet_disagrees(names): return f"Sheet disagrees on {_the(names)}."  # added to the count line


def tray_is(label): return f"This is the {label} tray."
def tray_switched(label): return f"This is the {label} tray. Switched."
def tray_busy(label): return f"This is the {label} tray. I can't switch while I'm busy."


def pack(name, expires):
    return f"{cap(name)} pack, expires {expires}." if expires else f"{cap(name)} pack, no expiry date."


def pack_expired(name, expires): return f"Expired: {name} pack, {expires}. Don't open it."
