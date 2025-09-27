# --------------------------
# AutoMod Settings
# --------------------------

# --------------------------
# Buffer / Sliding Window
# --------------------------
MAX_BUFFER = 5           # Number of recent messages stored per user
SUBSTRING_MIN = 3        # Minimum substring length to check
SUBSTRING_MAX = 50       # Maximum substring length to check

USER_COOLDOWN = 2        # Seconds between AutoMod checks per user

# --------------------------
# Punishment thresholds
# --------------------------
WARN_THRESHOLD = 1       # Number of infractions before warn
TIMEOUT_THRESHOLD = 3    # Number of infractions before timeout
BAN_THRESHOLD = 5        # Number of infractions before ban
TIMEOUT_DURATION = 600   # Timeout duration in seconds (10 mins)

# --------------------------
# Mega-server mode
# --------------------------
MEGA_SERVER_MODE = True  # Enables batch processing for high-traffic servers
BATCH_DELAY = 3          # Seconds to wait before processing message queue in batch

# --------------------------
# AI Toxicity detection
# --------------------------
AI_TOXIC_THRESHOLD = 0.6    # Score threshold for considering text toxic (0-1)

ALLOWED_SEXUAL_CONTEXT = [
    "i am gay", "i am straight", "i am bisexual", "sex education",
    "gender", "sexual orientation", "sexuality", "lgbt", "transgender",
    "cisgender", "non-binary", "queer", "damn", "hell", "shit", "crap",
    "pissed", "freaking", "frick", "heck", "freakin"
]

# --------------------------
# Mod Logging
# --------------------------
MOD_LOG_CHANNEL_ID = None  # Replace with your Discord mod channel ID

# --------------------------
# Validation
# --------------------------


def validate_config():
    """Validate all configuration values"""
    assert MAX_BUFFER > 0, "MAX_BUFFER must be positive"
    assert SUBSTRING_MIN >= 1, "SUBSTRING_MIN must be at least 1"
    assert SUBSTRING_MAX >= SUBSTRING_MIN, "SUBSTRING_MAX must be >= SUBSTRING_MIN"
    assert USER_COOLDOWN > 0, "USER_COOLDOWN must be positive"
    assert 0 <= AI_TOXIC_THRESHOLD <= 1, "AI_TOXIC_THRESHOLD must be between 0 and 1"
    assert WARN_THRESHOLD >= 0, "WARN_THRESHOLD must be non-negative"
    assert TIMEOUT_THRESHOLD >= 0, "TIMEOUT_THRESHOLD must be non-negative"
    assert BAN_THRESHOLD >= 0, "BAN_THRESHOLD must be non-negative"
    assert TIMEOUT_DURATION > 0, "TIMEOUT_DURATION must be positive"


# Run validation when module is imported
validate_config()
