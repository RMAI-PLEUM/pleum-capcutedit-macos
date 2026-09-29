# Thai caption rules

Normalize NFC. Preserve Thai combining marks, lexical words, English runs, numbers, names, URLs, and keyterms. Never start a caption with `ๆ`; merge it into the preceding token, timing, and source indices. Render no space before `ๆ`, one space after it before another lexical word, and no space before closing punctuation. Count/highlight `คำ+ๆ` as one word.
