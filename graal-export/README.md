# Graal Export

## Overview

Runs Native IMage's points-to analysis and dumps, per method, which fields it reads and which it writes
It runs on the standalone points-to analyzer `com.oracle.graal.pointsto.standalone`.

## Example Usage

```bash
./build.sh path/to/Demo.java [ more.java ... ]
DUMP_IR=out/out_name.json ./run-dump.sh Demo
```
