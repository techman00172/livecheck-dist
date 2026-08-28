#!/usr/bin/make -f
# Build and upload the LiveCheck demo to STM32F051 via SWD.
# Mirrors the nokia-5110-lcd project's proven Makefile.
# src/demo.fs -> source_in.fs -> (gema) -> upload.fs -> chip.

# Use ?= so a command-line MCU=STM32G031 overrides this default.
MCU ?= STM32F051

SRC_DIR = .
SOURCE_IN = source_in.fs
UPLOAD = upload.fs

GEMA = ../toolchain/gema
# The SVD database for the current chip lives in ../databases/<MCU>-svd.db
# (the -svd naming scheme).  The gema pipeline resolves CMSIS register names
# using the .pat files below, not the database — the database powers the
# editor's completions.  Change MCU + add your <MCU>.svd, then:
#   make databases            builds ../databases/<MCU>-svd.db for ANY STM32
SVD_SRC = $(SRC_DIR)/$(MCU).svd
SVD_DB_OUT = ../databases/$(MCU)-svd.db

# Build the SVD database for the current MCU from its .svd file.
# Usage:  MCU=STM32G031 make databases     (with demo/STM32G031.svd present)
databases:
	@test -f $(SVD_SRC) || (echo "ERROR: $(SVD_SRC) not found — put your SVD in demo/"; exit 1)
	../scripts/build-svd-db.sh $(MCU)

$(SVD_DB_OUT): $(SVD_SRC)
	../scripts/build-svd-db.sh $(MCU)

CONSTANTS_PAT = ../toolchain/patterns/constants.pat
STRIP_PAT = ../toolchain/patterns/strip.pat
REGISTERS_PAT = ../toolchain/patterns/registers.pat
BITFIELDS_PAT = ../toolchain/patterns/bitfields.pat

BITFIELDS_OUT = bitfields_out.fs
REGISTERS_OUT = registers_out.fs
CONSTANTS_OUT = constants_out.fs

PROJ_FILES = $(SRC_DIR)/demo.fs

all: check-ascii project upload

project: $(SOURCE_IN)

$(SOURCE_IN): $(PROJ_FILES)
	cat $(PROJ_FILES) > $(SOURCE_IN)
	@echo "Created $(SOURCE_IN)"

# Direct ST-Link upload (requires swdd.service stopped first).
quick: $(SOURCE_IN)
	@echo "=== Quick upload via swd2 ==="
	cat $(SOURCE_IN) | ../toolchain/swd2
	@echo "Upload complete"

# Full gema pipeline (resolves CMSIS names to addresses).
$(BITFIELDS_OUT): $(BITFIELDS_PAT) $(SOURCE_IN)
	$(GEMA) -t -nobackup -line $(SOURCE_IN) -f $(BITFIELDS_PAT) -out $(BITFIELDS_OUT)

$(REGISTERS_OUT): $(REGISTERS_PAT) $(BITFIELDS_OUT)
	$(GEMA) -t -nobackup -line $(BITFIELDS_OUT) -f $(REGISTERS_PAT) -out $(REGISTERS_OUT)

$(CONSTANTS_OUT): $(CONSTANTS_PAT) $(REGISTERS_OUT)
	$(GEMA) -t -nobackup -line $(REGISTERS_OUT) -f $(CONSTANTS_PAT) -out $(CONSTANTS_OUT)

$(UPLOAD): $(STRIP_PAT) $(CONSTANTS_OUT)
	$(GEMA) -t -nobackup -line $(CONSTANTS_OUT) -f $(STRIP_PAT) -out $(UPLOAD)

# Upload via the swdd daemon (headless).  ST-Link shared with Regmon.
upload: $(UPLOAD)
	@echo "=== Uploading via swdd daemon ==="
	cat $(UPLOAD) | python3 ../toolchain/swdd-upload.py
	@echo "Upload complete"

# Guard against non-ASCII bytes in the Forth sources (em-dashes etc.).
check-ascii: $(PROJ_FILES)
	@if grep -P -n '[^\x00-\x7F]' $(PROJ_FILES) ; then \
		echo "ERROR: non-ASCII bytes found above — Forth sources must be pure ASCII."; \
		echo "  (replace em-dashes/smart quotes with plain - and straight quotes)"; \
		exit 1; \
	else \
		echo "ASCII check passed: all sources pure ASCII."; \
	fi

clean:
	rm -f $(SOURCE_IN) $(BITFIELDS_OUT) $(REGISTERS_OUT) $(CONSTANTS_OUT) $(UPLOAD) .unresolved.tmp

.PHONY: all project quick upload check-ascii clean databases
