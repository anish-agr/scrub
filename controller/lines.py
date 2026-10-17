"""Every line Scrub says. Only the controller writes these (CONTRACTS: Event.say). Keep them short."""

STOPPED = "Stopped."
UNKNOWN = "Sorry, say that again?"
NOT_IN_SETTING = "That's not on this tray."
NOTHING_OUT = "Nothing's out."
BUSY = "One moment, I've got three waiting."
ERROR = "Something went wrong. Holding."
HAND_LOST = "Lost your hand. Holding."
PATH_BLOCKED = "Something's in the way. Holding."
OUT_OF_REACH = "That's out of my reach."
SHOW_HAND = "Hand open, please."
RESET = "Reset. Ready."
NEEDS_RESET = "I'm stopped. Reset me first."
SAY_GOT_IT = "Say got it when you have it."
SET_DOWN_FAILED = "Couldn't set it down. Holding."


def cap(s): return s[:1].upper() + s[1:]


def coming(name): return f"{cap(name)} coming."
def queued(name): return f"{cap(name)} next."
def handed(name): return None  # the arm arriving is enough; keeps the call quiet
def retry(name): return f"Missed the {name}, trying again."
def couldnt_pick(name): return f"I couldn't pick the {name}."
def not_on_tray(name): return f"I don't see the {name} on the tray."
def sharp_down(name): return f"{cap(name)} down."
def no_pull(name): return f"Setting the {name} down."
def set_down(name): return f"Setting the {name} down."
def no_hand(name): return f"No hand. {cap(name)} is at the safe spot."
def returned(name): return f"{cap(name)} back in its slot."
def couldnt_return(name): return f"I couldn't put the {name} back."


def count(names):
    if not names:
        return "Everything's on the tray."
    return "Out: " + ", ".join(names) + "."
