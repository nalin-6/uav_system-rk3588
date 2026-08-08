/* Field Profile Wizard — Auto-configure wizard for 5-point GPS field mapping.
   Captures anchor + 4 centerline points, generates profile JSON, binds it. */

window.UavFieldProfileWizard = (function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var api = window.UavApi;

  // ------------------------------------------------------------------
  // State
  // ------------------------------------------------------------------
  var currentStep = -1;        // -1=IDLE, 0-4=capture steps, 5=REVIEW
  var capturedPoints = [];     // [{step, name, lat, lon}]
  var wizardActive = false;
  var latestDrone = {};        // latest drone state from WebSocket

  // Step definitions
  var STEPS = [
    {id: "anchor", label: "起飞点 (Anchor)", guide: "请走到起飞点位置，确认 GPS 信号良好后点击“获取坐标”"},
    {id: "CL_1",   label: "中轴线点 1 (CL_1)", guide: "请走到中轴线第 1 个点（前方约 8~10 m），点击“获取坐标”"},
    {id: "CL_2",   label: "中轴线点 2 (CL_2)", guide: "请走到中轴线第 2 个点（前方约 16~20 m），点击“获取坐标”"},
    {id: "CL_3",   label: "中轴线点 3 (CL_3)", guide: "请走到中轴线第 3 个点（前方约 25~30 m），点击“获取坐标”"},
    {id: "CL_4",   label: "中轴线点 4 (CL_4)", guide: "请走到中轴线第 4 个点（前方约 33~40 m），点击“获取坐标”"},
  ];

  // GPS quality thresholds
  var GPS_MIN_FIX = 3;
  var GPS_MIN_SATS = 8;
  var GPS_MAX_EPH = 3.0;

  // ------------------------------------------------------------------
  // GPS display update (called from app.js renderStatus)
  // ------------------------------------------------------------------
  function onStatusUpdate(state) {
    if (!wizardActive) return;
    latestDrone = state.drone || {};
    updateGpsDisplay();
  }

  function updateGpsDisplay() {
    var d = latestDrone;
    setText($("fpWizLat"), d.lat != null ? Number(d.lat).toFixed(7) : "--");
    setText($("fpWizLon"), d.lon != null ? Number(d.lon).toFixed(7) : "--");
    setText($("fpWizFix"), d.gps_fix_type != null ? String(d.gps_fix_type) : "--");
    setText($("fpWizSats"), d.satellites_visible != null ? String(d.satellites_visible) : "--");
    setText($("fpWizEph"), d.gps_eph != null ? Number(d.gps_eph).toFixed(1) : "--");
    setText($("fpWizEpv"), d.gps_epv != null ? Number(d.gps_epv).toFixed(1) : "--");

    var valid = Boolean(d.global_position_valid);
    var el = $("fpWizGpsValid");
    if (el) {
      el.textContent = valid ? "YES" : "NO";
      el.className = valid ? "gps-good" : "gps-bad";
    }

    // Update GPS quality indicator on GPS panel
    var panel = $("fpWizardGpsPanel");
    if (panel) {
      var quality = getGpsQuality();
      panel.classList.remove("gps-quality-good", "gps-quality-marginal", "gps-quality-bad");
      panel.classList.add("gps-quality-" + quality);
    }

    // Enable/disable capture button based on GPS quality
    updateCaptureButtonState();
  }

  function getGpsQuality() {
    var d = latestDrone;
    var fix = Number(d.gps_fix_type) || 0;
    var sats = Number(d.satellites_visible) || 0;
    var eph = Number(d.gps_eph) || 999;
    if (fix >= GPS_MIN_FIX && sats >= GPS_MIN_SATS && eph <= GPS_MAX_EPH) return "good";
    if (fix >= 3 && sats >= 6) return "marginal";
    return "bad";
  }

  function updateCaptureButtonState() {
    var btn = $("fpWizardCapture");
    if (!btn) return;
    var quality = getGpsQuality();
    var valid = Boolean(latestDrone.global_position_valid);
    if (!valid || quality === "bad") {
      btn.disabled = true;
      btn.title = "GPS 信号不佳，无法采集";
    } else {
      btn.disabled = false;
      btn.title = "";
    }
  }

  // ------------------------------------------------------------------
  // Wizard lifecycle
  // ------------------------------------------------------------------
  function open() {
    wizardActive = true;
    currentStep = 0;
    capturedPoints = [];
    latestDrone = {};

    var overlay = $("fpWizardOverlay");
    if (overlay) overlay.style.display = "flex";

    // Reset step indicators
    updateStepIndicators();
    goToStep(0);

    // Show/hide buttons
    showButton("fpWizardCapture", true);
    showButton("fpWizardNext", false);
    showButton("fpWizardSave", false);
    showButton("fpWizardPrev", false);

    // Clear review
    var review = $("fpWizardReview");
    if (review) { review.style.display = "none"; review.innerHTML = ""; }
    var captured = $("fpWizardCaptured");
    if (captured) captured.innerHTML = "";

    setHint("");
  }

  function close() {
    wizardActive = false;
    currentStep = -1;
    var overlay = $("fpWizardOverlay");
    if (overlay) overlay.style.display = "none";
  }

  // ------------------------------------------------------------------
  // Step navigation
  // ------------------------------------------------------------------
  function goToStep(step) {
    currentStep = step;
    updateStepIndicators();

    if (step >= 0 && step < STEPS.length) {
      var stepDef = STEPS[step];
      setText($("fpWizardGuide"), "步骤 " + (step + 1) + "/5: " + stepDef.guide);

      // Show captured info for this step if already captured
      var captured = $("fpWizardCaptured");
      if (captured && capturedPoints[step]) {
        var pt = capturedPoints[step];
        captured.innerHTML = '<span class="gps-good">已采集:</span> ' +
          pt.lat.toFixed(7) + ', ' + pt.lon.toFixed(7);
      } else if (captured) {
        captured.innerHTML = '';
      }

      // Show/hide buttons
      showButton("fpWizardCapture", true);
      showButton("fpWizardNext", false);
      showButton("fpWizardSave", false);
      showButton("fpWizardPrev", step > 0);

      setHint("");
    }
  }

  function updateStepIndicators() {
    var stepsEl = $("fpWizardSteps");
    if (!stepsEl) return;
    var items = stepsEl.querySelectorAll(".fp-wizard-step");
    items.forEach(function (el) {
      var s = parseInt(el.getAttribute("data-step"));
      el.classList.remove("active", "completed");
      if (s === currentStep) el.classList.add("active");
      else if (s < currentStep || (capturedPoints[s] && currentStep === 5)) el.classList.add("completed");
    });
  }

  // ------------------------------------------------------------------
  // Capture point
  // ------------------------------------------------------------------
  function capturePoint() {
    if (currentStep < 0 || currentStep >= STEPS.length) return;

    var d = latestDrone;
    if (!d.global_position_valid) {
      setHint("GPS 位置无效，无法采集", "danger-text");
      return;
    }

    var lat = Number(d.lat);
    var lon = Number(d.lon);
    if (isNaN(lat) || isNaN(lon)) {
      setHint("GPS 数据异常", "danger-text");
      return;
    }

    // Warn if GPS quality is marginal
    var quality = getGpsQuality();
    if (quality === "marginal" && !confirm("GPS 质量一般（fix=" + d.gps_fix_type +
        " sats=" + d.satellites_visible + " eph=" + Number(d.gps_eph).toFixed(1) +
        "），仍要采集？")) {
      return;
    }

    var stepDef = STEPS[currentStep];
    capturedPoints[currentStep] = {
      step: stepDef.id,
      lat: lat,
      lon: lon,
    };

    // Show captured info
    var captured = $("fpWizardCaptured");
    if (captured) {
      captured.innerHTML = '<span class="gps-good">已采集:</span> ' +
        lat.toFixed(7) + ', ' + lon.toFixed(7) +
        ' (fix=' + d.gps_fix_type + ' sats=' + d.satellites_visible + ')';
    }

    updateStepIndicators();

    // Auto-advance to next step or show review
    if (currentStep < STEPS.length - 1) {
      setTimeout(function () { goToStep(currentStep + 1); }, 300);
    } else {
      showReview();
    }
  }

  // ------------------------------------------------------------------
  // Review
  // ------------------------------------------------------------------
  function showReview() {
    currentStep = 5;
    updateStepIndicators();

    setText($("fpWizardGuide"), "所有 5 个点已采集完成，请检查后点击“保存”");

    var review = $("fpWizardReview");
    if (review) {
      review.style.display = "block";
      var html = '<table class="fp-wizard-review-table"><thead><tr>' +
        '<th>步骤</th><th>名称</th><th>纬度</th><th>经度</th></tr></thead><tbody>';
      for (var i = 0; i < capturedPoints.length; i++) {
        var pt = capturedPoints[i];
        if (!pt) continue;
        var stepDef = STEPS[i];
        html += '<tr><td>' + (i + 1) + '</td>' +
          '<td>' + stepDef.label + '</td>' +
          '<td>' + pt.lat.toFixed(7) + '</td>' +
          '<td>' + pt.lon.toFixed(7) + '</td></tr>';
      }
      html += '</tbody></table>';
      review.innerHTML = html;
    }

    // Hide capture, show save
    showButton("fpWizardCapture", false);
    showButton("fpWizardNext", false);
    showButton("fpWizardSave", true);
    showButton("fpWizardPrev", true);

    setHint("");
  }

  // ------------------------------------------------------------------
  // Save profile (no auto-bind)
  // ------------------------------------------------------------------
  async function saveProfile() {
    // Build points array
    var points = [];
    for (var i = 0; i < capturedPoints.length; i++) {
      var pt = capturedPoints[i];
      if (!pt) {
        setHint("缺少第 " + (i + 1) + " 个点的坐标", "danger-text");
        return;
      }
      points.push({step: pt.step, lat: pt.lat, lon: pt.lon});
    }

    setHint("正在生成 Profile...", "");

    try {
      var createResult = await api.request("/api/field-profiles/auto-create", {
        method: "POST",
        body: JSON.stringify({points: points}),
      });

      if (!createResult.ok) {
        setHint("创建失败: " + (createResult.error || JSON.stringify(createResult.errors)), "danger-text");
        return;
      }

      var profileId = createResult.profile_id;
      setHint("Profile 已创建: " + profileId + " — 请到 Field Profile 面板手动绑定", "ok-text");

      // Refresh profile list
      if (window.UavFieldProfiles && window.UavFieldProfiles.fetchProfileList) {
        window.UavFieldProfiles.fetchProfileList();
      }

      // Auto-close after 3 seconds
      setTimeout(function () {
        close();
      }, 3000);
    } catch (e) {
      setHint("请求失败: " + e.message, "danger-text");
    }
  }

  // ------------------------------------------------------------------
  // Helpers
  // ------------------------------------------------------------------
  function setText(element, value, tone) {
    if (!element) return;
    element.textContent = value == null ? "--" : String(value);
    element.classList.remove("ok-text", "warning-text", "danger-text", "gps-good", "gps-bad");
    if (tone) element.classList.add(tone);
  }

  function showButton(id, visible) {
    var el = $(id);
    if (el) el.style.display = visible ? "" : "none";
  }

  function setHint(text, tone) {
    var el = $("fpWizardHint");
    if (!el) return;
    el.textContent = text || "";
    el.classList.remove("ok-text", "warning-text", "danger-text");
    if (tone) el.classList.add(tone);
  }

  // ------------------------------------------------------------------
  // Init
  // ------------------------------------------------------------------
  function init() {
    if ($("fpWizardClose")) $("fpWizardClose").onclick = close;
    if ($("fpWizardCancel")) $("fpWizardCancel").onclick = close;
    if ($("fpWizardCapture")) $("fpWizardCapture").onclick = capturePoint;
    if ($("fpWizardPrev")) $("fpWizardPrev").onclick = function () {
      if (currentStep > 0 && currentStep < 5) goToStep(currentStep - 1);
      else if (currentStep === 5) {
        // Back from review to step 4
        goToStep(STEPS.length - 1);
        var review = $("fpWizardReview");
        if (review) review.style.display = "none";
      }
    };
    if ($("fpWizardNext")) $("fpWizardNext").onclick = function () {
      if (currentStep >= 0 && currentStep < STEPS.length - 1) goToStep(currentStep + 1);
    };
    if ($("fpWizardSave")) $("fpWizardSave").onclick = saveProfile;
  }

  return {init: init, open: open, close: close, onStatusUpdate: onStatusUpdate};
})();
