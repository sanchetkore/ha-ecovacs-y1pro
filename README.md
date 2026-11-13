# ECOVACS DEEBOT Y1 Pro (`cqyi87`) Integration for Home Assistant

Custom component extending the official Home Assistant `ecovacs` integration with native support for the **ECOVACS DEEBOT Y1 Pro** (device class `cqyi87`, model `CARTESIAN_BLACK_INT`) and related numeric protocol models.

---

## Features for DEEBOT Y1 Pro

* 🧹 **Vacuum Entity:**
  * Clean (Start, Pause, Resume, Stop)
  * Return to Dock (Charge)
  * Real-time status (`docked`, `cleaning`, `returning`, `paused`, `idle`)
* 🔋 **Battery Level Sensor:** Live battery percentage.
* 💨 **Fan Speed Control:** Quiet, Normal, Max, Max+.
* 💧 **Water Amount Control:** Low, Medium, High.
* 🧽 **Consumables Life Sensors:**
  * Main Roll Brush remaining %
  * Side Brush remaining %
  * Filter remaining %
  * Unit Care / Sensors remaining %
* 🔒 **Controls & Switches:**
  * Child Lock switch
  * Do Not Disturb (DND) switch
  * Continuous Cleaning switch
  * Locate Robot button (plays voice/chime)
* 🛡️ **Zero Rust Requirement:** 100% pure-Python implementation. No native Rust compilation needed.
* 🔑 **Safe UI Authentication:** Authenticates directly via Home Assistant's standard UI flow with 2FA email verification support.

---

## Installation

### Method 1: Via HACS (Marketplace on latest HAOS) (Recommended)
1. Open **HACS** in your Home Assistant.
2. Click the three dots in the top right corner and select **Custom repositories**.
3. Add this repository URL:
   * **URL:** `https://github.com/sanchetkore/ha-ecovacs-y1pro`
   * **Category:** `Integration`
4. Search for **Ecovacs (DEEBOT Y1 Pro Support)** and click **Download**.
5. Restart Home Assistant.

### Method 2: Manual Git Clone / Copy
In your Home Assistant terminal (or SSH):
```bash
cd /config/custom_components
git clone https://github.com/<your-username>/ha-ecovacs-y1pro.git temp_ecovacs
cp -r temp_ecovacs/custom_components/ecovacs ./ecovacs
rm -rf temp_ecovacs
```
Restart Home Assistant.

---

## Configuration

1. In Home Assistant, go to **Settings** -> **Devices & Services**.
2. Click **Add Integration** and search for **Ecovacs**.
3. Enter your ECOVACS account username/email, password, and country code (e.g. `IN`, `US`, `DE`).
4. If prompted for a one-time verification code, check your email and enter the code into the Home Assistant dialog.
5. Your **DEEBOT Y1 Pro** will appear with all entities ready to use.
