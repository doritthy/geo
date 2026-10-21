// Copies CesiumJS runtime assets (web workers, widgets CSS, textures, third
// party WASM) into public/cesium, where window.CESIUM_BASE_URL points.
// Runs on postinstall so the copy always matches the installed version.
const fs = require('fs');
const path = require('path');

const src = path.join(__dirname, '..', 'node_modules', 'cesium', 'Build', 'Cesium');
const dest = path.join(__dirname, '..', 'public', 'cesium');

if (!fs.existsSync(src)) {
  console.warn('[copy-cesium] cesium not installed yet, skipping');
  process.exit(0);
}
for (const dir of ['Workers', 'ThirdParty', 'Assets', 'Widgets']) {
  fs.cpSync(path.join(src, dir), path.join(dest, dir), { recursive: true });
}
console.log('[copy-cesium] copied Cesium assets to public/cesium');
