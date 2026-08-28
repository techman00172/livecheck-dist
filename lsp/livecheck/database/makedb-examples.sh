#!/bin/sh
rm -f mecrisp-stellaris.db
sqlite3 mecrisp_stellaris.db < ./all.outputs.combined.txt 2>&1 | tee makerrors.log