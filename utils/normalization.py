# import unicodedata
# import re


# def normalize(text: str) -> str:
#     """
#     Normalize text for AutoMod:
#     - Lowercase
#     - Remove accents / Unicode variants
#     - Convert leetspeak
#     - Remove symbols / emojis but keep letters
#     """
#     text = text.lower()
#     text = unicodedata.normalize('NFKD', text).encode(
#         'ascii', 'ignore').decode('ascii')

#     replacements = {
#         "4": "a", "@": "a", "3": "e", "1": "i", "!": "i",
#         "0": "o", "$": "s", "5": "s", "7": "t", "ƒ": "f", "ß": "b", "ç": "c"
#     }

#     for k, v in replacements.items():
#         text = text.replace(k, v)

#     # Remove all non-letter/number characters
#     text = re.sub(r'[^a-z0-9]', '', text)

#     return text
