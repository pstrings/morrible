# from utils.punishments import handle_punishment
# from utils.normalization import normalize
# from config.automod_config import *
# import discord
# from discord.ext import commands
# from discord import Member, Guild
# from collections import defaultdict, deque
# import asyncio
# import time
# import re
# import sys
# import gc
# import hashlib
# from functools import lru_cache
# from typing import Optional, Deque, List, Dict, Any, cast

# # Initialize variables first to avoid unbound warnings
# TENSORFLOW_AVAILABLE = False
# model = None
# tf = None

# # Try to import tensorflow, fall back to rule-based if unavailable
# try:
#     import tensorflow as tf
#     import tensorflow_hub as hub
#     TENSORFLOW_AVAILABLE = True

#     # --------------------------
#     # Load Lightweight Model (CPU friendly)
#     # --------------------------
#     try:
#         # Using TensorFlow Hub's universal sentence encoder - much lighter and pure TensorFlow
#         print("🔄 Loading TensorFlow model...")

#         # Option 1: Universal Sentence Encoder (lightweight, good for toxicity detection)
#         model_url = "https://tfhub.dev/google/universal-sentence-encoder/4"
#         model = hub.KerasLayer(model_url)

#         # Test the model
#         test_embedding = model(["test sentence"])
#         print(f"✅ Loaded TensorFlow model successfully. Test embedding shape: {test_embedding.shape}")

#         # Configure TensorFlow for optimal CPU performance
#         tf.config.threading.set_intra_op_parallelism_threads(1)
#         tf.config.threading.set_inter_op_parallelism_threads(1)

#         print("✅ Loaded TensorFlow Universal Sentence Encoder model")

#     except Exception as e:
#         print(f"❌ Failed to load TensorFlow model: {e}")
#         TENSORFLOW_AVAILABLE = False
#         model = None
#         tf = None

# except ImportError:
#     print("TensorFlow not available, using rule-based detection only")
#     TENSORFLOW_AVAILABLE = False
#     tf = None


# # --------------------------
# # Configuration Validation
# # --------------------------


# def validate_automod_config():
#     """Validate configuration values"""
#     required_vars = ['MAX_BUFFER', 'SUBSTRING_MIN', 'SUBSTRING_MAX',
#                      'USER_COOLDOWN', 'AI_TOXIC_THRESHOLD']

#     for var in required_vars:
#         if not hasattr(sys.modules[__name__], var):
#             raise ValueError(f"Missing required config: {var}")

#     if SUBSTRING_MIN < 1 or SUBSTRING_MAX < SUBSTRING_MIN:
#         raise ValueError("Invalid substring range configuration")

#     if not (0 <= AI_TOXIC_THRESHOLD <= 1):
#         raise ValueError("AI_TOXIC_THRESHOLD must be between 0 and 1")


# validate_automod_config()

# # --------------------------
# # Buffers & locks with proper typing
# # --------------------------
# user_message_buffers: Dict[int, Deque[str]] = defaultdict(
#     lambda: deque(maxlen=MAX_BUFFER))
# user_sequence_buffers: Dict[int, Deque[str]] = defaultdict(
#     lambda: deque(maxlen=MAX_BUFFER * SUBSTRING_MAX))
# user_last_checked: Dict[int, float] = defaultdict(lambda: 0.0)
# user_locks: Dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
# message_queue: asyncio.Queue = asyncio.Queue()
# processing_lock: asyncio.Lock = asyncio.Lock()
# user_processing_times: Dict[int, float] = defaultdict(lambda: 0.0)

# # Type interface for BlacklistManager cog


# class BlacklistManagerCog(commands.Cog):
#     @property
#     def compiled_patterns(self) -> List[re.Pattern]:
#         return []


# class ModerationCog(commands.Cog):
#     pass


# class AutoMod(commands.Cog):
#     def __init__(self, bot: commands.Bot):
#         self.bot = bot
#         # Loaded dynamically
#         self.blacklist_cog: Optional[BlacklistManagerCog] = None
#         self.processed_hashes = set()

#         # Start background tasks
#         self.bot.loop.create_task(self.cleanup_inactive_users())
#         if MEGA_SERVER_MODE:
#             self.bot.loop.create_task(self.process_queue())

#     # ----------------------
#     # Text hashing for caching
#     # ----------------------
#     @lru_cache(maxsize=1000)
#     def get_text_hash(self, text: str) -> str:
#         """Create hash for text caching"""
#         return hashlib.md5(text.encode('utf-8', errors='ignore')).hexdigest()

#     # ----------------------
#     # Lightweight rule-based toxicity check
#     # ----------------------
#     def rule_based_toxicity_check(self, text: str) -> bool:
#         """Lightweight rule-based toxicity detection as fallback"""
#         if len(text.strip()) < SUBSTRING_MIN:
#             return False

#         text_lower = text.lower()

#         # Skip allowed contexts first
#         if self.allowed_context_check(text):
#             return False

#         # High-risk word patterns (common toxic terms)
#         high_risk_patterns = [
#             r'\b(?:fuck|shit|bitch|asshole|dick|pussy|cunt)\w*\b',
#             r'\b(?:kill|murder|hurt|harm)\s+(?:yourself|myself|themselves|us)\b',
#             r'\b(?:nigg|fag|retard)\w*\b',
#             r'\b(?:die\s+u|kys|kill\s+urself)\b',
#         ]

#         # Check high-risk patterns
#         for pattern in high_risk_patterns:
#             if re.search(pattern, text_lower, re.IGNORECASE):
#                 return True

#         # Check for excessive caps (yelling)
#         if len(text) > 10:
#             caps_count = sum(1 for c in text if c.isupper())
#             if caps_count > 5 and caps_count / len(text) > 0.6:
#                 return True

#         # Check for excessive repetition
#         words = text.split()
#         if len(words) > 5:
#             word_counts = {}
#             for word in words:
#                 word_counts[word] = word_counts.get(word, 0) + 1
#             most_common_count = max(word_counts.values()) if word_counts else 0
#             if most_common_count > len(words) * 0.4:  # 40% repetition
#                 return True

#         return False

#     # ----------------------
#     # Add message to buffers
#     # ----------------------
#     def add_message(self, user_id: int, content: str) -> List[str]:
#         if len(content.strip()) == 0:
#             return list(user_message_buffers[user_id])

#         # Prevent excessively long messages from bloating buffers
#         if len(content) > 1000:
#             content = content[:1000] + "..."

#         # Raw buffer (for regex across raw concatenation)
#         user_message_buffers[user_id].append(content)

#         # Normalized sequence buffer (for AI substring scanning / split-message detection)
#         normalized = normalize(content)
#         seq_buffer = user_sequence_buffers[user_id]
#         seq_buffer.extend(normalized)

#         # Efficient size management
#         max_size = MAX_BUFFER * SUBSTRING_MAX
#         while len(seq_buffer) > max_size:
#             # Remove oldest 25% when over limit
#             remove_count = max_size // 4
#             for _ in range(min(remove_count, len(seq_buffer))):
#                 seq_buffer.popleft()

#         return list(user_message_buffers[user_id])

#     # ----------------------
#     # Centralized regex check against raw combined text
#     # ----------------------
#     def regex_check(self, raw_text: str) -> bool:
#         if not self.blacklist_cog or not hasattr(self.blacklist_cog, 'compiled_patterns'):
#             return False
#         try:
#             # Use getattr to safely access the property
#             patterns = getattr(self.blacklist_cog, 'compiled_patterns', [])
#             for pat in patterns:
#                 if pat.search(raw_text):
#                     return True
#         except Exception as e:
#             print(f"Regex check error: {e}")
#         return False

#     # ----------------------
#     # Allowed context check (AI only; regex always wins)
#     # ----------------------
#     def allowed_context_check(self, text: str) -> bool:
#         text = text.lower()
#         return any(phrase in text for phrase in ALLOWED_SEXUAL_CONTEXT)

#     # ----------------------
#     # AI Toxicity check (Substring scanning) - Pure TensorFlow
#     # ----------------------
#     def ai_classify(self, text: str) -> bool:
#         """Pure TensorFlow classification without PyTorch dependencies"""
#         if not TENSORFLOW_AVAILABLE or model is None or tf is None:
#             return self.rule_based_toxicity_check(text)

#         if len(text.strip()) < SUBSTRING_MIN:
#             return False

#         # Check cache first
#         text_hash = self.get_text_hash(text)
#         if text_hash in self.processed_hashes:
#             return False

#         # If clearly benign identity/education phrasing, skip AI flagging
#         if self.allowed_context_check(text):
#             self.processed_hashes.add(text_hash)
#             return False

#         try:
#             # Universal Sentence Encoder expects a list of strings
#             embeddings = model([text])

#             # The model typically returns a tensor directly, but handle different formats
#             if isinstance(embeddings, dict):
#                 # Extract the actual embeddings from the dict
#                 embeddings = embeddings.get('outputs', embeddings.get(
#                     'embeddings', embeddings.get('encoding')))
#                 # If still a dict, take the first tensor value
#                 if isinstance(embeddings, dict):
#                     embeddings = list(embeddings.values())[0]

#             # Ensure we have a tensor for variance calculation
#             if hasattr(embeddings, 'numpy'):
#                 embedding_tensor = embeddings
#             else:
#                 embedding_tensor = tf.constant(embeddings)

#             # Calculate variance as toxicity indicator
#             embedding_variance = tf.math.reduce_variance(
#                 embedding_tensor).numpy()

#             # Adjust this threshold based on your testing
#             toxic_threshold = 0.02

#             result = embedding_variance > toxic_threshold
#             self.processed_hashes.add(text_hash)
#             return result

#         except Exception as e:
#             print(f"TensorFlow classification error: {e}")
#             return self.rule_based_toxicity_check(text)
#         finally:
#             # Clean up memory
#             gc.collect()

#     # ----------------------
#     # Queue message for batch processing
#     # ----------------------
#     async def queue_message(self, message: discord.Message):
#         await message_queue.put(message)

#     # ----------------------
#     # Batch queue processor
#     # ----------------------
#     async def process_queue(self):
#         while True:
#             await asyncio.sleep(BATCH_DELAY)
#             batch = []
#             while not message_queue.empty() and len(batch) < 10:  # Limit batch size
#                 batch.append(await message_queue.get())
#             if batch:
#                 async with processing_lock:
#                     for msg in batch:
#                         await self.process_user_buffer(msg.author.id, msg)

#     # ----------------------
#     # Process user buffer with sliding window - Optimized
#     # ----------------------
#     async def process_user_buffer(self, user_id: int, message: discord.Message):
#         now = time.time()

#         # Increased cooldown and minimum message requirement
#         if now - user_processing_times[user_id] < 30:
#             return

#         # Only process if user has sent enough messages
#         if len(user_message_buffers[user_id]) < 2:
#             return

#         user_processing_times[user_id] = now

#         try:
#             async with user_locks[user_id]:
#                 messages = list(user_message_buffers[user_id])
#                 if not messages:
#                     return

#                 # Combined raw text (for regex across actual characters & separators)
#                 combined_raw = " ".join(messages)

#                 # Quick regex gate: if any hard pattern matches raw, it's flagged
#                 regex_flagged = self.regex_check(combined_raw)

#                 ai_flagged = False
#                 if not regex_flagged:
#                     combined_normalized = "".join(
#                         user_sequence_buffers[user_id])
#                     if len(combined_normalized) >= SUBSTRING_MIN:
#                         # Check with optimized AI/rule-based method
#                         ai_flagged = self.ai_classify(combined_normalized)

#                 if not (regex_flagged or ai_flagged):
#                     return

#                 # Delete contributing recent messages from the channel history
#                 channel = message.channel
#                 deleted_count = 0
#                 try:
#                     async for m in channel.history(limit=30):
#                         if m.author.id == user_id and m.id != message.id and deleted_count < MAX_BUFFER:
#                             # Check if this message content is in our buffer
#                             for buffered_msg in messages:
#                                 if buffered_msg in m.content or m.content in buffered_msg:
#                                     await m.delete()
#                                     deleted_count += 1
#                                     break
#                 except Exception as e:
#                     print(f"Error deleting messages: {e}")

#                 # Clear buffers
#                 user_message_buffers[user_id].clear()
#                 user_sequence_buffers[user_id].clear()

#                 # Handle punishment via Moderation cog
#                 if isinstance(message.author, Member) and message.guild is not None:
#                     mod_cog = self.bot.get_cog("Moderation")
#                     infractions, action = await handle_punishment(
#                         self.bot,
#                         message,
#                         message.author,
#                         mod_cog=mod_cog,
#                         warn_threshold=WARN_THRESHOLD,
#                         timeout_threshold=TIMEOUT_THRESHOLD,
#                         ban_threshold=BAN_THRESHOLD,
#                         timeout_duration=TIMEOUT_DURATION
#                     )

#                     # Log to mod channel
#                     reason = "Regex violation" if regex_flagged else "AI toxicity"
#                     await self.log_mod(message.guild, message.author, f"{reason}: {action} (Infraction #{infractions})")
#                 else:
#                     print(
#                         f"Warning: Message author {message.author} is not a Member or guild is None")

#         except Exception as e:
#             print(f"Error processing buffer for user {user_id}: {e}")
#             # Clear buffers to prevent stuck state
#             user_message_buffers[user_id].clear()
#             user_sequence_buffers[user_id].clear()

#     # ----------------------
#     # Cleanup buffer for inactive users
#     # ----------------------
#     async def cleanup_inactive_users(self):
#         """Clean up buffers for users who haven't sent messages recently"""
#         while True:
#             await asyncio.sleep(3600)
#             try:
#                 current_time = time.time()
#                 user_ids = list(user_last_checked.keys())
#                 inactive_users = [
#                     uid for uid in user_ids
#                     if current_time - user_last_checked[uid] > 3600
#                 ]
#                 for uid in inactive_users:
#                     user_message_buffers.pop(uid, None)
#                     user_sequence_buffers.pop(uid, None)
#                     user_last_checked.pop(uid, None)
#                     user_locks.pop(uid, None)
#                     user_processing_times.pop(uid, None)

#                 # Clean up processed hashes cache periodically
#                 if len(self.processed_hashes) > 5000:
#                     self.processed_hashes.clear()
#                     self.get_text_hash.cache_clear()

#                 print(
#                     f"AutoMod cleanup: Removed {len(inactive_users)} inactive users")
#             except Exception as e:
#                 print(f"Error during AutoMod cleanup: {e}")

#     # ----------------------
#     # Log to mod channel
#     # ----------------------
#     async def log_mod(self, guild: Guild, user: discord.abc.User, reason: str):
#         """Log AutoMod actions to the moderation channel"""
#         if not MOD_LOG_CHANNEL_ID:
#             return

#         try:
#             channel = guild.get_channel(MOD_LOG_CHANNEL_ID)
#             if channel and isinstance(channel, discord.TextChannel):
#                 embed = discord.Embed(
#                     title="🚨 AutoMod Action",
#                     color=discord.Color.red(),
#                     timestamp=discord.utils.utcnow()
#                 )
#                 embed.add_field(
#                     name="User", value=f"{user} ({user.id})", inline=False)
#                 embed.add_field(name="Action", value=reason, inline=False)
#                 await channel.send(embed=embed)
#         except Exception as e:
#             print(f"Error logging to mod channel: {e}")

#     # ----------------------
#     # On message listener
#     # ----------------------
#     @commands.Cog.listener()
#     async def on_message(self, message: discord.Message):
#         if message.author.bot or not message.guild:
#             return

#         # Load BlacklistManager dynamically with type casting
#         if not self.blacklist_cog:
#             blacklist_cog = self.bot.get_cog("BlacklistManager")
#             if blacklist_cog:
#                 # Type cast to fix the Pylance issue
#                 self.blacklist_cog = cast(BlacklistManagerCog, blacklist_cog)
#             else:
#                 print("Warning: BlacklistManager cog not found")
#                 return

#         user_id = message.author.id
#         self.add_message(user_id, message.content)

#         now = time.time()
#         if now - user_last_checked[user_id] >= USER_COOLDOWN:
#             user_last_checked[user_id] = now
#             if MEGA_SERVER_MODE:
#                 await self.queue_message(message)
#             else:
#                 asyncio.create_task(self.process_user_buffer(user_id, message))


# async def setup(bot: commands.Bot):
#     await bot.add_cog(AutoMod(bot))
