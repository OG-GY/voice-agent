"""Reply wording. Several variants per key; the variant is picked by turn number (no randomness).

Fields: {hon} = ", sir"/", ma'am" at most every few turns, {HON} = always when known.
"""

T: dict[str, tuple[str, ...]] = {
    "greet": (
        "Thank you for calling {restaurant}. I can book a table, cancel a booking, or answer "
        "questions about our hours. How may I help you?",
        "Welcome to {restaurant}. How can I help you today?",
    ),
    "greet_restart": ("No problem, let's start over. How can I help you?",),
    "ask_date": ("Which day would you like?", "What day were you thinking of?"),
    "ask_date_options": ("Would that be {options}?",),
    "ask_time": ("What time would you like?", "And what time suits you?"),
    "ask_time_range": ("For {range} I have {times}. Which would you like?",),
    "ask_time_range_none": (
        "I don't have anything free for {range}. What other time would suit you?",
    ),
    "ask_party": ("How many people will be joining?", "And for how many people?"),
    "ask_name": ("May I have a name for the booking?", "Under what name should I book it?"),
    "ask_phone": ("And a contact phone number, please?", "Could I take a phone number as well?"),
    "ask_seating_full": (
        "Certainly{hon}, I'll book a table for you. Would you like a private family table, "
        "a window-side table, or shall I book a general one?",
    ),
    "ask_seating_short": ("Would you prefer a private table, a window table, or a general one?",),
    "suggest_min": ("Our {seat} tables are for parties of {limit} or more.",),
    "suggest_max": ("Our {seat} tables seat up to {limit}.",),
    "suggest_one": (" For {party} I'd suggest {what}. Shall I book that?",),
    "suggest_many": (" For {party} I can offer {what}. Which would you prefer?",),
    "ask_title": ("Thank you. Is that Mr., Mrs. or Ms. {name}? Or just the name is fine.",),
    "ask_ref": (
        "Could you give me your booking reference? It starts with C P, followed by four digits.",
    ),
    "ack_lead": ("Got it, ", "Okay, "),
    "ack_corrected": ("Sure{hon}, I've updated it to ",),
    "available": ("That's available.", "Good news, that's available."),
    "confirm_booking": (
        "Let me confirm{hon}: {what}, under {who}, phone {phone}. Shall I book it?",
    ),
    "offer_lead": ("Sorry{hon}, {seating} isn't available at {time}.",),
    "offer_lost": ("Sorry{hon}, that table was just taken.",),
    "offer_many": (" I do have {options}. Would you like one of those?",),
    "offer_one": (" I do have {options}. Shall I book that instead?",),
    "offer_reask": ("Which one would you like: {options}?",),
    "booking_done": (
        "Perfect{HON}! Your booking is confirmed: {what}. Your reference is {ref}. "
        "Please keep it in case you need to change anything.",
    ),
    "cancel_confirm": (
        "I found your booking: {what}, under {who}. Would you like me to cancel it?",
    ),
    "cancel_done": ("Done{HON}. Booking {ref} for {what} has been cancelled.",),
    "cancel_already": ("That booking, {ref}, was already cancelled.",),
    "ask_cancel_name": ("Thank you. And what name is the booking under?",),
    "verification_failed": ("I couldn't match those details. Let's try again.",),
    "handoff_verification": (
        "I'm sorry, I can't verify those details. Let me pass you to a member of our team: "
        "they will call you back in two to three minutes. Goodbye!",
    ),
    "try_later": (
        "I'm sorry, I can't continue with cancellations right now. Please try again later. Goodbye!",
    ),
    "unavailable": (
        "I'm sorry, our booking system isn't available right now. Our team will call you back in "
        "two to three minutes. Please answer that call and confirm your reservation. I can still "
        "tell you our opening hours in the meantime.",
    ),
    "offer_booking": ("Would you like me to book a table for you?",),
    "anything_else": ("Is there anything else I can help you with?",),
    "kept": ("Alright{hon}, I've left your booking as it is.",),
    "ask_change": ("Of course{hon}. What would you like to change?",),
    "out_of_scope": (
        "Sorry{HON}, I can't help with that. If you'd like to book a table, please let me know.",
        "I'm afraid I can only help with table bookings, cancellations and our opening hours.",
    ),
    "reprompt": (
        "Sorry, I didn't catch that.",
        "Sorry, could you say that again?",
        "I'm having trouble hearing you. Could you repeat that?",
    ),
    "help": (
        "I can book a table, cancel an existing booking, or tell you our opening hours and "
        "whether tables are free. What would you like to do?",
    ),
    "hold": ("Sure{hon}, take your time.",),
    "warn_unsaved": ("Just so you know{hon}, your booking isn't saved yet. Shall I finish it?",),
    "switch": ("Shall I drop the booking we were making and cancel an existing one instead?",),
    "presence": ("Are you still there?",),
    "apology": ("My apologies{HON}.",),
    "goodbye": (
        "Thank you for calling {restaurant}{HON}. Goodbye!",
        "Goodbye{HON}, have a lovely day!",
    ),
    "handoff_human": (
        "Of course. Let me pass you to a member of our team: they will call you back in two to "
        "three minutes. Please answer that call and confirm your reservation. Goodbye!",
    ),
    "handoff_party": (
        "For groups of more than {max} people I'll need to pass you to our events team. They will "
        "call you back in two to three minutes. Please answer that call and confirm your "
        "reservation. Goodbye!",
    ),
    "handoff_failures": (
        "I'm sorry, I'm having trouble understanding. Let me pass you to a member of our team: "
        "they will call you back in two to three minutes. Please answer that call and confirm "
        "your reservation. Goodbye!",
    ),
    "handoff_scope": (
        "I'm afraid I can only help with bookings. Let me pass you to a member of our team: they "
        "will call you back in two to three minutes. Please answer that call and confirm your "
        "reservation. Goodbye!",
    ),
    "fallback": ("Sorry, I didn't quite get that. Could you say it again?",),
}
