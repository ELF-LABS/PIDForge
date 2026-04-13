# PIDForge

**Autonomous FPV drone tuning agent** — connects to your flight controller via WebBluetooth, analyzes blackbox logs with signal processing + LLM reasoning, and pushes optimized PID settings back to your quad. Your drone gets better every flight.

Built by [ELF Labs](https://github.com/ELF-LABS) in Harlan, Iowa.

## What It Does

1. **Connect** — Phone browser connects to your FC via Bluetooth (SpeedyBee adapter or built-in BLE)
2. **Fly** — Go rip some packs
3. **Analyze** — PIDForge pulls your blackbox log, runs FFT noise analysis + step response + motor diagnostics
4. **Recommend** — LLM reads the analysis + your flight history + Betaflight source knowledge → generates specific PID/filter changes with reasoning
5. **Apply** — One tap sends the CLI diff to your FC
6. **Repeat** — Each flight makes the next one better

No laptop needed. No manual tuning spreadsheets. Your quad tunes itself.

## Features

- **WebBluetooth MSP** — Direct browser-to-FC communication via Nordic UART Service
- **Signal Analysis** — FFT noise profiling, step response, motor output balance
- **LLM Tuning** — AI-powered recommendations grounded in Betaflight firmware knowledge
- **Flight History** — ChromaDB tracks every flight, spots trends across sessions
- **Flight Scoring** — Objective 0-100 quality score per flight
- **Tuning Wizard** — 12-phase step-by-step guided tuning for manual approach
- **Simulator** — Mock FC + synthetic flights for testing without hardware
- **PWA** — Install on your phone's home screen

## Status

**Alpha — built in under 24 hours.** The core signal analysis, MSP protocol, and LLM integration work. The WebBluetooth bridge and simulator have been smoke-tested but not field-tested with real hardware yet. Expect rough edges.

We're shipping early because we believe in building in public. PRs, bug reports, and flight data are all welcome.

## Quick Start

### Requirements
- Python 3.10+
- A Betaflight FC with BLE adapter (SpeedyBee or similar)
- Phone with Chrome (Android) or [Bluefy](https://apps.apple.com/us/app/nicebluetooth-ble-browser/id1435492523) (iOS)

### Install
```bash
git clone https://github.com/ELF-LABS/PIDForge.git
cd PIDForge
pip install flask chromadb numpy scipy pyserial websockets
```

### Run
```bash
python pidforge_web.py
```

Open `http://localhost:5050` on your phone (or via Tailscale for field use).

### Simulator (no hardware needed)
```bash
cd simulator
python mock_fc.py &
cd ..
python pidforge_web.py
```
Open browser → click "SIM MODE" → "Connect FC" → upload test data or generate synthetic flights.

## Architecture

```
Phone (WebBluetooth)
  ↕ BLE / Nordic UART Service
Flight Controller (Betaflight MSP)
  ↕ Blackbox data + PID config
PIDForge Server
  ├── Signal Analysis (FFT, step response, noise floor)
  ├── Flight Scorer (objective 0-100 quality metric)
  ├── LLM Tuner (Qwen/Gemma/any OpenAI-compatible endpoint)
  ├── ChromaDB (flight history + trend tracking)
  ├── Recommender (rule-based fallback)
  └── PIDForge Claw (autonomous watch + analyze loop)
```

## LLM Configuration

PIDForge works with any OpenAI-compatible API endpoint. Set via environment variables:

```bash
export PIDFORGE_TWIN_URL="http://localhost:11434/v1"  # Ollama
export PIDFORGE_TWIN_MODEL="qwen3.5:4b"
```

Works with: Ollama, llama.cpp, SGLang, vLLM, LM Studio, OpenAI API, or any compatible endpoint.

## MSP Commands Used

| Command | Code | Purpose |
|---------|------|---------|
| MSP_PID | 112 | Read current PIDs |
| MSP_SET_PID | 202 | Write new PIDs |
| MSP_PID_ADVANCED | 94 | Read D-min, feedforward, etc. |
| MSP_SET_PID_ADVANCED | 95 | Write advanced PID settings |
| MSP_FILTER_CONFIG | 92 | Read filter settings |
| MSP_SET_FILTER_CONFIG | 93 | Write filter settings |
| MSP_EEPROM_WRITE | 250 | Save to flash |
| MSP_DATAFLASH_SUMMARY | 70 | Blackbox storage info |
| MSP_DATAFLASH_READ | 71 | Download blackbox data |

## Roadmap

- [x] Signal analysis (FFT, step response, noise)
- [x] Rule-based PID recommendations
- [x] ChromaDB flight history
- [x] LLM-powered tuning with reasoning
- [x] WebBluetooth MSP bridge
- [x] Phone-first PWA
- [x] Mock FC simulator
- [x] Flight quality scoring
- [ ] Real BLE flight test
- [ ] iNav CLI support
- [ ] ArduPilot CLI support
- [ ] Multi-quad profiles
- [ ] Community preset sharing
- [ ] Training data from real flights → adapter improvement

## Contributing

PRs welcome. If you're an FPV pilot with blackbox logs, we want your data (anonymized) to improve the tuning engine.

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

[Apache 2.0](LICENSE)

## Credits

- [Orangebox](https://github.com/nicoquain/orangebox) — Betaflight blackbox log parser
- [Betaflight](https://github.com/betaflight/betaflight) — The firmware that makes FPV possible
- Built with signal analysis math ported from [PID-Analyzer](https://github.com/Plasmatree/PID-Analyzer)

---

*PIDForge is an [ELF Labs](https://github.com/ELF-LABS) project. Sovereign AI infrastructure from Harlan, Iowa.*
