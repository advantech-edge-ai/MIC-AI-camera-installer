# Advantech Camera Driver Installer

在 Jetson（MIC 系列）上用 GUI 安裝相機驅動。驅動清單與驅動包執行時從 GitHub repo
[advantech-edge-ai/MIC-AI-camera-driver](https://github.com/advantech-edge-ai/MIC-AI-camera-driver)
抓（`internet_list.sh` + Release Assets），工具本身與該 repo 的 `install_camera.sh` / `online_mode.sh` 獨立。

## 安裝

支援 MIC-AI 系列 Jetson（Orin / Thor，JetPack 6 以上已實機驗證），需要網路連到 GitHub。

```bash
wget -O /tmp/advantech-camera-installer_all.deb \
  https://github.com/advantech-edge-ai/MIC-AI-camera-installer/releases/latest/download/advantech-camera-installer_all.deb
sudo apt install /tmp/advantech-camera-installer_all.deb
```

裝好後從應用程式選單開啟「Advantech Camera Driver Installer」，或在終端機執行 `advantech-camera-installer`
（SSH 連線、沒有桌面時會自動改用終端機選單）。

移除：`sudo apt remove advantech-camera-installer`（已安裝的相機驅動不受影響）。

## 開發

### 執行

```bash
python3 -m camera_installer            # 有 $DISPLAY → GUI，否則終端機選單
python3 -m camera_installer --tui      # 強制終端機選單
python3 -m camera_installer --dry-run  # 下載 / 校驗 / 解壓都做，但不以 root 執行安裝
```

需求：Python ≥ 3.8、`python3-tk`（GUI）、`pkexec`（GUI 提權）或 `sudo`（終端機）。無第三方套件。

### 在非 Jetson 機器上測試

用環境變數假裝成某台機器（變數名稱與 MIC-AI-camera-driver 的腳本相同）：

```bash
echo "MIC-733AO_32G_Orin_6.2_V1.0.0, 1:abc" > /tmp/version
printf "TEGRA_CHIPID 0x23\n" > /tmp/nv_boot_control.conf
CF_VERSION_FILE=/tmp/version CF_NV_BOOT_CONF=/tmp/nv_boot_control.conf \
  python3 -m camera_installer --dry-run
```

`--list-url <URL 或本機檔案>`（或 `CF_LIST_URL`）可改用別的清單。

### 結構

| 檔案 | 用途 |
|---|---|
| `camera_installer/catalog.py` | 抓 / 用 regex 解析 `internet_list.sh`（不 source 執行） |
| `camera_installer/device.py` | `/opt/version` 機型 + JetPack、`TEGRA_CHIPID` SoC 家族 |
| `camera_installer/matching.py` | 機型配對規則（741/743 共用 742 包等） |
| `camera_installer/checks.py` | 啟動環境檢查（GUI / TUI 共用） |
| `camera_installer/installer.py` | 下載 → MD5 → 解壓 → 安裝流程、安裝紀錄 |
| `camera_installer/helpers/install_driver.sh` | 唯一以 root 執行的部分（pkexec / sudo） |
| `camera_installer/gui.py` | Tkinter 四步驟畫面 |
| `camera_installer/tui.py` | 無 `$DISPLAY` 時的終端機選單 |
| `tools/render_logo.py` | 開發用：把 logo SVG 轉成 Tk 能讀的 PNG（需 Pillow） |
| `tools/make_icons.py` | 開發用：把 `app_icon_192.png` 縮成各尺寸應用程式圖示（需 Pillow） |
| `tools/build_deb.sh` | 用 `dpkg-deb` 打包成 `build/advantech-camera-installer_<版本>_all.deb` |

### 打包

```bash
bash tools/build_deb.sh
```

版本號取自 `camera_installer/__init__.py` 的 `__version__`。安裝時 deb 放 `/tmp` 再 `sudo apt install /tmp/<deb>`，
可避免 apt 的 `_apt` 權限提示（放家目錄也能裝，只是會多一行提示）。

### 測試

```bash
python3 -m unittest discover -s tests -v
```

### 執行時寫入的位置

- 下載快取：`~/.cache/advantech-camera-installer/`
- 安裝 log、上次安裝紀錄：`~/.local/share/advantech-camera-installer/`
- 驅動安裝目錄：`/opt/advantech/camera_framework/vendors/<vendor>/<sensor>/<platform>/<board>/<jetpack>`
