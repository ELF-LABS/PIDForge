# Contributing to PIDForge

Thanks for wanting to help make FPV tuning better for everyone.

## How to Contribute

### Flight Data
The most valuable contribution is real blackbox data. If you have .BFL files from test flights, we'd love anonymized logs to improve the tuning engine. Open an issue with the "flight-data" label.

### Code
1. Fork the repo
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes
4. Test with the simulator (`python simulator/mock_fc.py`)
5. Submit a PR

### Bug Reports
Open an issue with:
- Your FC board and firmware version
- BLE adapter type
- Browser and OS
- Steps to reproduce

### Feature Requests
Open an issue with the "enhancement" label. We're especially interested in:
- iNav / ArduPilot CLI support
- New signal analysis techniques
- Better tuning heuristics from experienced pilots
- UI/UX improvements for field use

## Code Style
- Python 3.10+
- Docstrings on public functions
- Print-based logging: `print("[INFO] ...", "[WARN] ...", "[ERROR] ...")`

## Ethics
PIDForge is a tuning tool for recreational and commercial FPV flight. We do not accept contributions that enable autonomous weapons systems, surveillance, or any application designed to cause harm. See our [license](LICENSE) for details.

## License
By contributing, you agree that your contributions will be licensed under the Apache 2.0 License.
