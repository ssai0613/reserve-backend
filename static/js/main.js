/**
 * ReServe Admin Web Portal - Master JS Controller (v3.2 - 100% Database Driven)
 */

document.addEventListener('DOMContentLoaded', () => {
  if (window.lucide) {
    window.lucide.createIcons();
  }

  if (document.getElementById('userGrowthChart')) {
    initDashboardCharts();
  }
  
  initAdminLogin();
  setupGlobalListeners();
  initCalendarPickers();
  updateRoleStats('Consumer'); 
});

// =========================================================
// DASHBOARD CHARTS & HEADER MENUS
// =========================================================
function initDashboardCharts() {
  const growthCanvas = document.getElementById('userGrowthChart');
  const donutCanvas = document.getElementById('trafficDonutChart');

  let labels = ['May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct'];
  let counts = [0, 0, 0, 0, 0, 0];
  let donutData = [1, 1, 1];

  try {
    if (document.body.dataset.chartLabels) {
      labels = JSON.parse(document.body.dataset.chartLabels);
    }
    if (document.body.dataset.chartCounts) {
      counts = JSON.parse(document.body.dataset.chartCounts);
    }
    if (document.body.dataset.donutCounts) {
      const parsedDonut = JSON.parse(document.body.dataset.donutCounts);
      if (parsedDonut.some(v => v > 0)) donutData = parsedDonut;
    }
  } catch (e) {
    console.log("Chart data parse fallback:", e);
  }

  if (growthCanvas && window.Chart) {
    new Chart(growthCanvas, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [{
          label: 'New Platform Registrations',
          data: counts,
          borderColor: '#1B4D3E',
          backgroundColor: 'rgba(58, 130, 109, 0.15)',
          borderWidth: 3,
          fill: true,
          tension: 0.35,
          pointBackgroundColor: '#1B4D3E',
          pointRadius: 4
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          y: { beginAtZero: true, ticks: { precision: 0 } }
        }
      }
    });
  }

  if (donutCanvas && window.Chart) {
    new Chart(donutCanvas, {
      type: 'doughnut',
      data: {
        labels: ['Bakeshops', 'Market Vendors', 'Others'],
        datasets: [{
          data: donutData,
          backgroundColor: ['#1B4D3E', '#3A826D', '#EBB338'],
          borderWidth: 0
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '70%',
        plugins: { legend: { display: false } }
      }
    });
  }
}

window.toggleNotifMenu = function() {
  const menu = document.getElementById('notifDropdown');
  const adminMenu = document.getElementById('adminDropdown');
  if (adminMenu) adminMenu.classList.add('hidden');
  if (menu) menu.classList.toggle('hidden');
};

window.toggleAdminMenu = function() {
  const menu = document.getElementById('adminDropdown');
  const notifMenu = document.getElementById('notifDropdown');
  if (notifMenu) notifMenu.classList.add('hidden');
  if (menu) menu.classList.toggle('hidden');
};

window.toggleMobileNav = function() {
  const nav = document.getElementById('mainNavbar');
  if (nav) nav.classList.toggle('hidden');
};

window.openAdminProfile = function() {
  const adminMenu = document.getElementById('adminDropdown');
  if (adminMenu) adminMenu.classList.add('hidden');
  window.openModal('adminProfileModal');
};


// =========================================================
// LIVE USER TRANSACTION FETCHER
// =========================================================


// =========================================================
// AUTH & MODAL HELPERS
// =========================================================
function initAdminLogin() {
  const loginForm = document.getElementById('loginForm');
  if (!loginForm) return;

  loginForm.addEventListener('submit', async function(e) {
    e.preventDefault(); 
    const email = document.getElementById('email').value;
    const password = document.getElementById('pw').value;
    const errorEl = document.getElementById('formError');
    const submitBtn = loginForm.querySelector('button[type="submit"]');
    const originalBtnText = submitBtn.innerHTML;

    errorEl.classList.add('hidden');
    submitBtn.innerHTML = 'Authenticating...';

    try {
      const response = await fetch('/api/accounts/login/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_email: email, user_pass: password })
      });

      if (response.ok) {
        const data = await response.json();
        if (data.role !== 'Admin') {
          errorEl.textContent = "Unauthorized: Administrator access required.";
          errorEl.classList.remove('hidden');
          submitBtn.innerHTML = originalBtnText;
          return;
        }
        localStorage.setItem('admin_access_token', data.access);
        localStorage.setItem('admin_refresh_token', data.refresh);
        window.location.href = "/dashboard/";
      } else {
        const errData = await response.json().catch(() => ({}));
        errorEl.textContent = errData.error || "Invalid email or password.";
        errorEl.classList.remove('hidden');
        submitBtn.innerHTML = originalBtnText;
      }
    } catch (error) {
      errorEl.textContent = "Network error. Please check your connection.";
      errorEl.classList.remove('hidden');
      submitBtn.innerHTML = originalBtnText;
    }
  });
}

window.openModal = function(modalId) {
  const modal = document.getElementById(modalId);
  if (!modal) return;
  modal.classList.remove('hidden');
  modal.classList.add('flex');
  document.body.classList.add('overflow-hidden');
  if (window.lucide) window.lucide.createIcons();
};

window.closeModal = function(modalId) {
  const modal = document.getElementById(modalId);
  if (!modal) return;
  modal.classList.add('hidden');
  modal.classList.remove('flex');
  document.body.classList.remove('overflow-hidden');
};

window.toggleModal = function(modalId) {
  const modal = document.getElementById(modalId);
  if (!modal) return;
  if (modal.classList.contains('hidden')) {
    window.openModal(modalId);
  } else {
    window.closeModal(modalId);
  }
};

window.toggleSection = function(sectionId) {
  const el = document.getElementById(sectionId);
  if (!el) return;
  el.classList.toggle('hidden');
};

function initCalendarPickers() {
  if (window.flatpickr) {
    flatpickr(".date-range-picker", {
      mode: "range",
      dateFormat: "Y-m-d",
      altInput: true,
      altFormat: "F j, Y",
      conjunction: " to ",
      onChange: function(selectedDates) {
        if (selectedDates.length === 2) {
          filterByCalendarRange(selectedDates[0], selectedDates[1]);
        }
      }
    });
  }
}

window.filterByCalendarRange = function(startDate, endDate) {
  const visibleTable = document.querySelector('table.user-role-table:not(.hidden)');
  if (!visibleTable) return;
  
  const rows = visibleTable.querySelectorAll('tbody tr:not(.empty-row)');
  endDate.setHours(23, 59, 59);

  rows.forEach(row => {
    const dateStr = row.getAttribute('data-date');
    if (dateStr) {
      const rowDate = new Date(dateStr);
      row.style.display = (rowDate >= startDate && rowDate <= endDate) ? '' : 'none';
    }
  });
};

window.clearCalendarFilter = function() {
  const pickerInput = document.querySelector('.date-range-picker');
  if (pickerInput && pickerInput._flatpickr) {
    pickerInput._flatpickr.clear();
  }
  const visibleTable = document.querySelector('table.user-role-table:not(.hidden)');
  if (!visibleTable) return;
  
  const rows = visibleTable.querySelectorAll('tbody tr:not(.empty-row)');
  rows.forEach(row => row.style.display = '');
};

window.triggerSortByCriteria = function(selectElement) {
  const criteria = selectElement.value;
  const visibleTable = document.querySelector('table.user-role-table:not(.hidden)');
  if (!visibleTable || !criteria) return;

  const tbody = visibleTable.querySelector('tbody');
  const rows = Array.from(tbody.querySelectorAll('tr:not(.empty-row)'));
  const isAscending = !criteria.includes('desc');

  rows.sort((a, b) => {
    if (criteria.includes('date')) {
      const dateA = new Date(a.getAttribute('data-date') || 0);
      const dateB = new Date(b.getAttribute('data-date') || 0);
      return isAscending ? dateA - dateB : dateB - dateA;
    }
    if (criteria.includes('status')) {
      const statA = a.getAttribute('data-status') || '';
      const statB = b.getAttribute('data-status') || '';
      return isAscending ? statA.localeCompare(statB) : statB.localeCompare(statA);
    }
    if (criteria.includes('tier')) {
      const tA = parseInt(a.getAttribute('data-tier') || 0);
      const tB = parseInt(b.getAttribute('data-tier') || 0);
      return isAscending ? tA - tB : tB - tA;
    }
    
    const nameA = a.children[1]?.textContent.trim().toLowerCase() || '';
    const nameB = b.children[1]?.textContent.trim().toLowerCase() || '';
    return isAscending ? nameA.localeCompare(nameB) : nameB.localeCompare(nameA);
  });
  
  rows.forEach(row => tbody.appendChild(row));
};

function setupGlobalListeners() {
  window.addEventListener('click', (event) => {
    if (event.target.classList.contains('modal-overlay')) {
      event.target.classList.add('hidden');
      event.target.classList.remove('flex');
      document.body.classList.remove('overflow-hidden');
    }
  });

  const searchInputs = document.querySelectorAll('input[placeholder*="Search"]');
  searchInputs.forEach(input => {
    input.addEventListener('input', handleLiveSearch);
  });
}

function handleLiveSearch(event) {
  const query = event.target.value.toLowerCase();
  const visibleTable = document.querySelector('table.user-role-table:not(.hidden)');
  if (!visibleTable) return;
  
  const rows = visibleTable.querySelectorAll('tbody tr:not(.empty-row)');
  rows.forEach(row => {
    const searchData = row.getAttribute('data-search') || row.textContent.toLowerCase();
    row.style.display = searchData.includes(query) ? '' : 'none';
  });
}

window.switchRoleTab = function(roleName, element) {
  const tabs = document.querySelectorAll('.role-tab-btn');
  tabs.forEach(tab => {
    tab.classList.remove('bg-white', 'text-[#1B4D3E]', 'shadow-sm', 'border-b-2', 'border-[#1B4D3E]');
    tab.classList.add('text-gray-400', 'hover:text-[#1B4D3E]');
  });
  element.classList.remove('text-gray-400', 'hover:text-[#1B4D3E]');
  element.classList.add('bg-white', 'text-[#1B4D3E]', 'shadow-sm', 'border-b-2', 'border-[#1B4D3E]');

  const tables = document.querySelectorAll('.user-role-table');
  tables.forEach(table => table.classList.add('hidden'));

  const targetId = `table-${roleName.toLowerCase().replace(/\s+/g, '')}`;
  const activeTable = document.getElementById(targetId);
  if (activeTable) {
    activeTable.classList.remove('hidden');
    updateRoleStats(roleName);
  }
};

function updateRoleStats(roleName) {
  const tableId = `table-${roleName.toLowerCase().replace(/\s+/g, '')}`;
  const table = document.getElementById(tableId);
  if (!table) return;

  const rows = table.querySelectorAll('tbody tr:not(.empty-row)');
  let total = rows.length;
  let active = 0;
  let suspendedOrPending = 0;

  rows.forEach(row => {
    const status = row.getAttribute('data-status') || '';
    if (status.includes('active')) {
      active++;
    } else {
      suspendedOrPending++;
    }
  });

  const statCards = document.querySelectorAll('main .grid-cols-1.sm\\:grid-cols-3 > div');
  if (statCards.length >= 3) {
    statCards[0].querySelector('h3').textContent = total;
    statCards[1].querySelector('h3').textContent = active;
    statCards[2].querySelector('h3').textContent = suspendedOrPending;
    
    statCards[0].querySelector('p').textContent = `Total ${roleName}s`;
    statCards[1].querySelector('p').textContent = `Active ${roleName}s`;
    statCards[2].querySelector('p').textContent = `Pending / Flagged`;
  }
}

// =========================================================
// 1. CONSUMER MODAL (WITH LIVE TRANSACTIONS)
// =========================================================
window.openConsumerModal = function(btn) {
  const rawId = btn.dataset.rawId || '';
  document.getElementById('activeConsumerRawId').value = rawId;
  document.getElementById('consViewName').textContent = btn.dataset.name || 'Consumer';
  document.getElementById('consViewFullName').textContent = btn.dataset.name || 'Consumer';
  document.getElementById('consViewId').textContent = btn.dataset.id || 'ID';
  document.getElementById('consViewEmail').textContent = btn.dataset.email || 'N/A';
  document.getElementById('consViewPhone').textContent = btn.dataset.phone || 'Not Provided';
  document.getElementById('consViewAddress').textContent = btn.dataset.address || 'Not Provided';
  document.getElementById('consViewDate').textContent = btn.dataset.date || 'N/A';
  
  const statusEl = document.getElementById('consStatusBadge');
  const statusStr = (btn.dataset.status || 'Active').toUpperCase();
  if (statusEl) {
    statusEl.textContent = statusStr;
    statusEl.className = statusStr === 'SUSPENDED'
      ? "bg-rose-500 text-white px-3 py-1 rounded-full text-[10px] font-black uppercase"
      : "bg-emerald-500 text-white px-3 py-1 rounded-full text-[10px] font-black uppercase";
  }

  if (btn.dataset.name) {
    document.getElementById('consInitials').textContent = btn.dataset.name.charAt(0).toUpperCase();
  }

  if (rawId) {
    loadLiveUserTransactions('Consumer', rawId, 'consumerTransactionsBody', 6);
  }

  window.openModal('consumerViewModal');
};

// =========================================================
// 2. MERCHANT REVIEW MODAL (WITH EDITABLE OCR)
// =========================================================
window.setOcrInputsEditable = function(isEditable) {
  const inputs = document.querySelectorAll('.ocr-editable-input');
  const toggleBtn = document.getElementById('ocrEditToggleBtn');
  inputs.forEach(input => {
    input.readOnly = !isEditable;
    if (isEditable) {
      input.parentElement.classList.remove('bg-gray-50', 'border-gray-100');
      input.parentElement.classList.add('bg-white', 'border-amber-400', 'ring-2', 'ring-amber-200');
    } else {
      input.parentElement.classList.add('bg-gray-50', 'border-gray-100');
      input.parentElement.classList.remove('bg-white', 'border-amber-400', 'ring-2', 'ring-amber-200');
    }
  });
  if (toggleBtn) {
    toggleBtn.innerHTML = isEditable
      ? `<i data-lucide="check" class="w-3 h-3"></i> Lock Edits`
      : `<i data-lucide="pencil" class="w-3 h-3"></i> Manual Edit OCR`;
    if (window.lucide) window.lucide.createIcons();
  }
};

window.toggleOcrManualEdit = function() {
  const firstInput = document.getElementById('ocrDetectName');
  if (!firstInput) return;
  const willBeEditable = firstInput.readOnly;
  window.setOcrInputsEditable(willBeEditable);
  if (willBeEditable) {
    firstInput.focus();
  }
};


// =========================================================
// 3. MERCHANT VIEW MODAL (WITH LIVE TRANSACTIONS & EXPIRY)
// =========================================================

// =========================================================
// 4. FOOD BANK PENDING & ACTIVE MODALS
// =========================================================
window.openFoodBankPendingModal = function(btn) {
  document.getElementById('pendingFoodBankId').value = btn.dataset.id;
  document.getElementById('fbPendingModalTitle').textContent = btn.dataset.name || 'Food Bank';
  document.getElementById('fbPendingName').textContent = btn.dataset.name || 'N/A';
  document.getElementById('fbPendingAddress').textContent = btn.dataset.address || 'Not Provided';
  document.getElementById('fbPendingContact').textContent = btn.dataset.contact || 'Not Provided';
  document.getElementById('fbPendingPhone').textContent = btn.dataset.phone || 'Not Provided';
  document.getElementById('fbPendingHotline').textContent = btn.dataset.hotline || 'N/A';
  document.getElementById('fbPendingEmail').textContent = btn.dataset.email || 'N/A';
  document.getElementById('fbPendingDate').textContent = btn.dataset.date || 'N/A';
  document.getElementById('fbPendingExpiry').textContent = btn.dataset.expiry || 'N/A';

  const fileBtn = document.getElementById('fbPendingPermitBtn');
  if (fileBtn) {
    fileBtn.onclick = () => window.open(btn.dataset.permit, '_blank');
  }

  window.openModal('foodBankPendingModal');
};


// =========================================================
// 5. COMPLIANCE API ACTIONS (APPROVE, REJECT, SUSPEND, NOTIFY)
// =========================================================
function getCSRFToken() {
  let cookieValue = null;
  if (document.cookie && document.cookie !== '') {
    const cookies = document.cookie.split(';');
    for (let i = 0; i < cookies.length; i++) {
      const cookie = cookies[i].trim();
      if (cookie.substring(0, 10) === ('csrftoken=')) {
        cookieValue = decodeURIComponent(cookie.substring(10));
        break;
      }
    }
  }
  return cookieValue;
}

window.themeAlert = function(title, message, isSuccess = true) {
  return new Promise((resolve) => {
    document.getElementById('themeAlertTitle').textContent = title;
    document.getElementById('themeAlertMessage').textContent = message;
    
    const iconWrap = document.getElementById('themeAlertIconWrap');
    const icon = document.getElementById('themeAlertIcon');
    
    if (isSuccess) {
      iconWrap.className = "mx-auto w-14 h-14 rounded-full bg-[#E7F1EC] text-[#3A826D] flex items-center justify-center mb-3";
      icon.setAttribute('data-lucide', 'check-circle');
    } else {
      iconWrap.className = "mx-auto w-14 h-14 rounded-full bg-rose-100 text-rose-500 flex items-center justify-center mb-3";
      icon.setAttribute('data-lucide', 'alert-triangle');
    }
    if (window.lucide) window.lucide.createIcons();

    const modal = document.getElementById('themeAlertModal');
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    
    document.getElementById('themeAlertBtn').onclick = () => {
      modal.classList.add('hidden');
      modal.classList.remove('flex');
      resolve();
    };
  });
};

window.themeConfirm = function(title, message) {
  return new Promise((resolve) => {
    document.getElementById('themeConfirmTitle').textContent = title;
    document.getElementById('themeConfirmMessage').textContent = message;
    
    const modal = document.getElementById('themeConfirmModal');
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    
    document.getElementById('themeConfirmCancel').onclick = () => {
      modal.classList.add('hidden');
      modal.classList.remove('flex');
      resolve(false);
    };
    
    document.getElementById('themeConfirmOk').onclick = () => {
      modal.classList.add('hidden');
      modal.classList.remove('flex');
      resolve(true);
    };
  });
};

window.executeApprove = async function(role = 'Merchant') {
  const accountId = role === 'FoodBank'
    ? document.getElementById('pendingFoodBankId').value
    : document.getElementById('pendingMerchantId').value;

  const isConfirmed = await themeConfirm(
    "Approve Registration", 
    `Are you sure you want to officially approve ${role} ID ${accountId} and save the verified details to the database?`
  );
  if (!isConfirmed) return;

  const payload = { action: 'approve', role: role };

  if (role === 'Merchant') {
    payload.ocr_edits = {
      business_name: document.getElementById('ocrDetectName').value,
      permit_number: document.getElementById('ocrDetectPermitNo').value,
      lgu_anchor: document.getElementById('ocrDetectLGU').value,
      business_address: document.getElementById('ocrDetectAddress').value,
      nature_of_business: document.getElementById('ocrDetectNature').value,
      calendar_year: document.getElementById('ocrDetectYear').value.replace(/^Year\s+/i, ''),
      representative: document.getElementById('ocrDetectRep').value,
      expiry_date: document.getElementById('ocrDetectExpiry').value
    };
  }

  try {
    const response = await fetch(`/api/accounts/admin/merchant/${accountId}/approval/`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRFToken() },
      body: JSON.stringify(payload)
    });

    if (response.ok) {
      await themeAlert("Registration Approved!", `${role} account ${accountId} is now active and verified.`, true);
      window.location.reload(); 
    } else {
      await themeAlert("Approval Failed", "The server rejected the approval.", false);
    }
  } catch (error) {
    await themeAlert("Network Error", "Could not reach the server. Please check your connection.", false);
  }
};

window.executeReject = async function(role = 'Merchant') {
  const accountId = role === 'FoodBank'
    ? document.getElementById('pendingFoodBankId').value
    : document.getElementById('pendingMerchantId').value;

  const reasonSelect = document.getElementById(role === 'FoodBank' ? 'fbRejectReasonSelect' : 'rejectReasonSelect');
  const reason = reasonSelect.value;
  
  if (!reason) {
    await themeAlert("Missing Information", "Please select a specific reason for rejection from the dropdown menu before proceeding.", false);
    return;
  }

  const isConfirmed = await themeConfirm(
    "Reject & Request Resubmission", 
    `Reject ${role} ID ${accountId}? An email will be sent instructing them to resubmit their document due to: "${reason}".`
  );
  if (!isConfirmed) return;

  try {
    const response = await fetch(`/api/accounts/admin/merchant/${accountId}/approval/`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRFToken() },
      body: JSON.stringify({ action: 'reject', role: role, reason: reason })
    });

    if (response.ok) {
      await themeAlert("Resubmission Requested", "The applicant has been emailed with a link to upload a new document.", true);
      window.location.reload(); 
    } else {
      await themeAlert("Rejection Failed", "The server failed to update the status.", false);
    }
  } catch (error) {
    await themeAlert("Network Error", "Could not reach the server.", false);
  }
};

window.executeConsumerSuspend = async function() {
  const consId = document.getElementById('activeConsumerRawId').value;
  const reason = document.getElementById('consumerSuspendReason').value;

  if (!reason) {
    await themeAlert("Select Reason", "Please select a suspension reason from the dropdown first.", false);
    return;
  }

  const isConfirmed = await themeConfirm(
    "Suspend Consumer Account",
    `Suspend Consumer CID-${consId} for "${reason}"? They will be notified via email with an appeal link.`
  );
  if (!isConfirmed) return;

  try {
    const response = await fetch(`/api/accounts/admin/merchant/${consId}/approval/`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRFToken() },
      body: JSON.stringify({ action: 'suspend', role: 'Consumer', reason: reason })
    });

    if (response.ok) {
      await themeAlert("Consumer Suspended", "Account suspended and appeal link dispatched to their email.", true);
      window.location.reload();
    } else {
      await themeAlert("Action Failed", "Could not suspend the consumer account.", false);
    }
  } catch (error) {
    await themeAlert("Network Error", "Could not reach the server.", false);
  }
};

window.executeSuspend = async function(role = 'Merchant') {
  const accountId = role === 'FoodBank'
    ? document.getElementById('activeFoodBankId').value
    : document.getElementById('activeMerchantId').value;

  const reasonSelect = document.getElementById(role === 'FoodBank' ? 'fbSuspendReason' : 'merchantSuspendReason');
  const reason = reasonSelect.value;

  if (!reason) {
    await themeAlert("Select Reason", "Please select a suspension reason from the dropdown before suspending.", false);
    return;
  }

  const isConfirmed = await themeConfirm(
    `Suspend ${role} Account`,
    `Suspend ${role} ID ${accountId} due to "${reason}"? They will receive an email notification with an appeal link to request reactivation.`
  );
  if (!isConfirmed) return;

  try {
    const response = await fetch(`/api/accounts/admin/merchant/${accountId}/approval/`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRFToken() },
      body: JSON.stringify({ action: 'suspend', role: role, reason: reason })
    });

    if (response.ok) {
      await themeAlert("Account Suspended", `The ${role} has been suspended and emailed an appeal link.`, true);
      window.location.reload();
    } else {
      await themeAlert("Suspension Failed", "The server could not process the suspension.", false);
    }
  } catch (error) {
    await themeAlert("Network Error", "Could not reach the server.", false);
  }
};

window.openSendNotificationModal = function(role = 'Merchant', selectRenewalOption = false) {
  document.getElementById('notifTargetRole').value = role;
  if (selectRenewalOption) {
    const renewalRadio = document.getElementById('renewalNotifRadio');
    if (renewalRadio) renewalRadio.checked = true;
  }
  window.openModal('sendNotificationModal');
};

window.executeSendNotification = async function() {
  const role = document.getElementById('notifTargetRole').value || 'Merchant';
  const accountId = role === 'FoodBank'
    ? document.getElementById('activeFoodBankId').value
    : document.getElementById('activeMerchantId').value;

  const selectedRadio = document.querySelector('input[name="premadeNotifOption"]:checked');
  if (!selectedRadio) return;

  const message = selectedRadio.value;
  const isRenewal = selectedRadio.getAttribute('data-renewal') === 'true';

  try {
    const response = await fetch(`/api/accounts/admin/merchant/${accountId}/approval/`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRFToken() },
      body: JSON.stringify({
        action: 'notify',
        role: role,
        reason: message,
        is_renewal: isRenewal
      })
    });

    if (response.ok) {
      window.closeModal('sendNotificationModal');
      await themeAlert("Notification Sent!", `Pre-made compliance notice has been dispatched to ${role} ID ${accountId}.`, true);
      if (isRenewal) window.location.reload();
    } else {
      await themeAlert("Failed to Send", "Could not dispatch the notification.", false);
    }
  } catch (error) {
    await themeAlert("Network Error", "Could not reach the server.", false);
  }
};

// =========================================================
// 6. FOOD LISTING, DONATION, PAYOUT & ANNOUNCEMENT ACTIONS
// =========================================================


window.flagFoodListingModal = async function() {
  const rawId = document.getElementById('currentFoodRawId').value;
  await fetch('/api/accounts/admin/portal-action/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRFToken() },
    body: JSON.stringify({ module: 'listing', action: 'flag', id: rawId })
  });
  window.closeModal('foodModal');
  window.location.reload();
};

window.removeFoodListingModal = async function() {
  const rawId = document.getElementById('currentFoodRawId').value;
  const rowId = document.getElementById('currentFoodRowId').value;
  window.closeModal('foodModal');
  await window.removeFoodListing(rawId, rowId);
};



window.openDonationPostingModal = function(hubName, produce, vol, date, beneficiaries, addr, rowId, rawId, isFbOrg) {
  document.getElementById('modalPostingHubTitle').textContent = hubName;
  document.getElementById('modalProduceType').textContent = produce;
  document.getElementById('modalIntakeVol').textContent = vol;
  document.getElementById('modalBeneficiaries').textContent = beneficiaries;
  document.getElementById('modalHubAddr').textContent = addr;
  document.getElementById('modalSubDate').textContent = date;

  const approveBtn = document.getElementById('modalApproveReqBtn');
  if (approveBtn) {
    approveBtn.onclick = () => {
      window.closeModal('donationPostingModal');
      window.handleDonationAction('approve', rawId, rowId, isFbOrg);
    };
  }
  window.openModal('donationPostingModal');
};

window.openDonationTransactionModal = function(txId, merchant, hub, items, date, courier, status, rawId) {
  document.getElementById('modalTxId').textContent = txId;
  document.getElementById('modalTxMerchant').textContent = merchant;
  document.getElementById('modalTxHub').textContent = hub;
  document.getElementById('modalTxItems').textContent = items;
  document.getElementById('modalTxDate').textContent = date;
  document.getElementById('modalTxStatusBadge').textContent = status;

  const delivBtn = document.getElementById('modalDeliveredBtn');
  if (delivBtn) {
    delivBtn.onclick = () => {
      window.closeModal('donationTxModal');
      window.handleDonationAction('deliver', rawId, `tx-row-${txId}`, false);
    };
  }
  const flagBtn = document.getElementById('modalFlagTxBtn');
  if (flagBtn) {
    flagBtn.onclick = () => {
      window.closeModal('donationTxModal');
      window.handleDonationAction('flag', rawId, `tx-row-${txId}`, false);
    };
  }
  window.openModal('donationTxModal');
};

window.handleDonationAction = async function(action, rawId, rowId, isFbOrg = false) {
  await fetch('/api/accounts/admin/portal-action/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRFToken() },
    body: JSON.stringify({ module: 'donation', action: action, id: rawId, is_fb_org: isFbOrg })
  });
  window.location.reload();
};

// =========================================================
// ENHANCED MODAL-ONLY ALERTS, LOGOUT CONFIRM, OCR MATCHING,
// ADMIN PASSWORD RESET, MERCHANT DIRECTORY & PAYOUT MODAL
// =========================================================

window.saveAdminProfile = async function() {
  const emailInput = document.getElementById('adminProfileEmailInput');
  if (!emailInput) return;

  try {
    const res = await fetch('/api/accounts/admin/profile/update/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRFToken() },
      body: JSON.stringify({ email: emailInput.value })
    });
    if (res.ok) {
      window.closeModal('adminProfileModal');
      await themeAlert('Profile Updated', 'Admin profile email updated in database!', true);
    } else {
      await themeAlert('Update Failed', 'Failed to update admin email.', false);
    }
  } catch (e) {
    await themeAlert('Network Error', 'Network error while saving profile.', false);
  }
};

window.handleLogout = async function() {
  const isSure = await themeConfirm(
    'Confirm Logout',
    'Are you sure you want to log out of the ReServe Administrator Portal?'
  );
  if (!isSure) return;
  localStorage.removeItem('admin_access_token');
  localStorage.removeItem('admin_refresh_token');
  window.location.href = '/login/';
};

window.sendAdminPasswordResetEmail = async function() {
  const btn = document.getElementById('sendAdminResetLinkBtn');
  const feedback = document.getElementById('adminResetFeedback');
  if (!btn || !feedback) return;

  btn.disabled = true;
  btn.textContent = 'Sending Link...';
  feedback.classList.add('hidden');

  try {
    const res = await fetch('/api/accounts/forgot-password/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_admin: true })
    });
    const data = await res.json();
    feedback.classList.remove('hidden');
    if (res.ok) {
      feedback.className = 'p-3 rounded-xl font-bold text-[11px] bg-emerald-50 text-emerald-800 border border-emerald-200';
      feedback.textContent = data.message || 'Password reset link sent to reserve.org.com@gmail.com!';
      btn.textContent = 'Link Sent ✓';
    } else {
      feedback.className = 'p-3 rounded-xl font-bold text-[11px] bg-rose-50 text-rose-700 border border-rose-200';
      feedback.textContent = data.error || 'Could not send reset email.';
      btn.disabled = false;
      btn.textContent = 'Send Reset Link to Email';
    }
  } catch (err) {
    feedback.classList.remove('hidden');
    feedback.className = 'p-3 rounded-xl font-bold text-[11px] bg-rose-50 text-rose-700 border border-rose-200';
    feedback.textContent = 'Network error while requesting password reset.';
    btn.disabled = false;
    btn.textContent = 'Send Reset Link to Email';
  }
};

window.compareOcrTokens = function(inputtedStr, extractedStr) {
  const cleanA = (inputtedStr || '').toLowerCase().replace(/[^a-z0-9\s]/g, '').trim();
  const cleanB = (extractedStr || '').toLowerCase().replace(/[^a-z0-9\s]/g, '').trim();
  if (!cleanA || !cleanB || cleanB === 'not detected' || cleanB === 'unverified') return false;
  if (cleanA.includes(cleanB) || cleanB.includes(cleanA)) return true;
  const wordsA = cleanA.split(/\s+/).filter(w => w.length > 2);
  const wordsB = cleanB.split(/\s+/).filter(w => w.length > 2);
  const shared = wordsA.filter(w => wordsB.includes(w));
  return shared.length > 0;
};

window.setMatchBadgeState = function(badgeId, isMatch) {
  const el = document.getElementById(badgeId);
  if (!el) return;
  if (isMatch) {
    el.textContent = '✓ Match';
    el.className = 'text-[9px] font-black px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800 border border-emerald-300';
  } else {
    el.textContent = '⚠ Check / Mismatch';
    el.className = 'text-[9px] font-black px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 border border-amber-300';
  }
};

window.updateOcrMatchIndicators = function() {
  const regName = document.getElementById('pendingBusName')?.textContent || '';
  const regAddr = document.getElementById('pendingAddress')?.textContent || '';
  const regRep = document.getElementById('pendingContact')?.textContent || '';

  const ocrName = document.getElementById('ocrDetectName')?.value || '';
  const ocrAddr = document.getElementById('ocrDetectAddress')?.value || '';
  const ocrRep = document.getElementById('ocrDetectRep')?.value || '';

  window.setMatchBadgeState('ocrMatchNameBadge', window.compareOcrTokens(regName, ocrName));
  window.setMatchBadgeState('ocrMatchAddrBadge', window.compareOcrTokens(regAddr, ocrAddr));
  window.setMatchBadgeState('ocrMatchRepBadge', window.compareOcrTokens(regRep, ocrRep));
};

window.openPendingModal = function(btn) {
  const merchantId = btn.dataset.id || '';
  document.getElementById('pendingMerchantId').value = merchantId;
  document.getElementById('pendingModalTitle').textContent = `Merchant Verification — ${btn.dataset.name || 'Merchant'}`;
  document.getElementById('pendingBusName').textContent = btn.dataset.name || 'N/A';
  document.getElementById('pendingMerchType').textContent = btn.dataset.type || 'N/A';
  document.getElementById('pendingDate').textContent = btn.dataset.date || 'N/A';
  document.getElementById('pendingAddress').textContent = btn.dataset.address || 'Not Provided';
  document.getElementById('pendingContact').textContent = btn.dataset.contact || 'Not Provided';
  document.getElementById('pendingPhone').textContent = btn.dataset.phone || 'Not Provided';
  document.getElementById('pendingHotline').textContent = btn.dataset.hotline || 'N/A';
  document.getElementById('pendingEmail').textContent = btn.dataset.email || 'N/A';

  let ocrData = {};
  try {
    ocrData = JSON.parse(btn.dataset.ocr || '{}');
  } catch (e) {
    ocrData = {};
  }

  const confScore = ocrData.confidence_score !== undefined ? Number(ocrData.confidence_score).toFixed(1) : '85.0';
  const confBadge = document.getElementById('ocrConfidenceScore');
  if (confBadge) {
    confBadge.textContent = `Confidence: ${confScore}%`;
  }

  const permitPath = btn.dataset.permit || '';
  const docNameEl = document.getElementById('ocrDocName');
  if (docNameEl) {
    const cleanFileName = permitPath.split('/').pop() || 'Business Permit';
    docNameEl.textContent = cleanFileName;
  }

  const fileBtn = document.getElementById('pendingPermitBtn');
  if (fileBtn) {
    fileBtn.onclick = () => window.open(permitPath, '_blank');
  }

  document.getElementById('ocrDetectName').value = ocrData.business_name || btn.dataset.name || 'Not Detected';
  document.getElementById('ocrDetectPermitNo').value = ocrData.permit_number || 'Not Detected';
  document.getElementById('ocrDetectLGU').value = ocrData.lgu_anchor || 'Cebu City LGU';
  document.getElementById('ocrDetectAddress').value = ocrData.business_address || btn.dataset.address || 'Not Detected';
  document.getElementById('ocrDetectNature').value = ocrData.nature_of_business || btn.dataset.type || 'Food Establishment';
  document.getElementById('ocrDetectYear').value = ocrData.calendar_year ? `Year ${ocrData.calendar_year}` : 'Year 2026';
  document.getElementById('ocrDetectRep').value = ocrData.representative || btn.dataset.contact || 'Not Detected';
  document.getElementById('ocrDetectExpiry').value = ocrData.expiry_date !== 'Not Detected' && ocrData.expiry_date
    ? ocrData.expiry_date
    : (btn.dataset.expiry || '2026-12-31');

  window.setOcrInputsEditable(false);
  window.updateOcrMatchIndicators();
  window.openModal('merchantPendingModal');
};

window.filterListingsByBucket = function(bucket, btnEl) {
  document.querySelectorAll('.listing-bucket-tab').forEach(t => {
    t.className = 'listing-bucket-tab px-5 py-2.5 text-xs font-bold rounded-2xl text-gray-500 hover:text-[#1B4D3E]';
  });
  btnEl.className = 'listing-bucket-tab px-5 py-2.5 text-xs font-black rounded-2xl bg-white text-[#1B4D3E] shadow-sm border-b-2 border-[#1B4D3E]';

  document.querySelectorAll('tr.listing-row').forEach(row => {
    if (bucket === 'all' || row.dataset.bucket === bucket) {
      row.style.display = '';
    } else {
      row.style.display = 'none';
    }
  });
};

window.removeFoodListing = async function(rawId, rowId) {
  const isSure = await themeConfirm("Remove Food Listing", "Are you sure you want to permanently remove this food listing from the database?");
  if (!isSure) return;
  await fetch('/api/accounts/admin/portal-action/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRFToken() },
    body: JSON.stringify({ module: 'listing', action: 'delete', id: rawId })
  });
  const row = document.getElementById(rowId);
  if (row) row.remove();
  await themeAlert("Listing Removed", "The food listing has been removed.", true);
};

window.openPayoutApprovalModal = function(btn) {
  document.getElementById('poModalRawId').value = btn.dataset.rawId;
  document.getElementById('poModalIsWallet').value = btn.dataset.isWallet;
  document.getElementById('poModalTitle').textContent = `Withdrawal ${btn.dataset.id} — ${btn.dataset.merchant}`;
  document.getElementById('poModalMerchant').textContent = `${btn.dataset.merchant} (${btn.dataset.merchantId})`;
  document.getElementById('poModalTier').textContent = btn.dataset.tier;
  document.getElementById('poModalContact').textContent = `${btn.dataset.contact} (${btn.dataset.phone})`;
  document.getElementById('poModalEmail').textContent = btn.dataset.email;
  document.getElementById('poModalBalance').textContent = btn.dataset.balance;
  document.getElementById('poModalRequested').textContent = btn.dataset.requested;
  document.getElementById('poModalFee').textContent = btn.dataset.fee;
  document.getElementById('poModalNet').textContent = btn.dataset.net;
  document.getElementById('poModalChannel').textContent = btn.dataset.channel;
  document.getElementById('poModalAcctNum').textContent = btn.dataset.accountNum;
  document.getElementById('poModalAcctName').textContent = btn.dataset.accountName;

  const refInput = document.getElementById('poModalRefInput');
  refInput.value = btn.dataset.ref || '';
  const isSettled = (btn.dataset.status || '').toLowerCase() !== 'pending';
  refInput.readOnly = isSettled;

  const footer = document.getElementById('poModalActionsFooter');
  if (footer) {
    footer.style.display = isSettled ? 'none' : 'flex';
  }

  window.openModal('payoutApprovalModal');
};

window.submitPayoutDecision = async function(action) {
  const rawId = document.getElementById('poModalRawId').value;
  const isWallet = document.getElementById('poModalIsWallet').value === 'true';
  const refNum = document.getElementById('poModalRefInput').value.trim();

  if (action === 'approve' && !refNum) {
    await themeAlert("Reference Number Required", "Please enter the official GCash/Maya transfer reference number before approving this withdrawal.", false);
    return;
  }

  const isConfirmed = await themeConfirm(
    action === 'approve' ? "Confirm Payout Transfer" : "Reject Withdrawal Request",
    action === 'approve'
      ? `Approve this withdrawal with Transfer Reference # "${refNum}"? The merchant will be notified immediately.`
      : "Are you sure you want to reject this withdrawal request?"
  );
  if (!isConfirmed) return;

  const res = await fetch('/api/accounts/admin/portal-action/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRFToken() },
    body: JSON.stringify({
      module: 'payout',
      action: action,
      id: rawId,
      is_merchant_wallet: isWallet,
      reference_number: refNum
    })
  });
  const data = await res.json().catch(() => ({}));
  if (res.ok) {
    window.closeModal('payoutApprovalModal');
    await themeAlert("Payout Updated", data.message || "Withdrawal status updated.", true);
    window.location.reload();
  } else {
    await themeAlert("Action Failed", data.error || "Could not process payout decision.", false);
  }
};

window.handleAnnouncementSubmit = async function(e) {
  e.preventDefault();
  const audience = document.getElementById('announcementAudience').value;
  const title = document.getElementById('announcementTitle').value;
  const body = document.getElementById('announcementBody').value;

  const res = await fetch('/api/accounts/admin/portal-action/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRFToken() },
    body: JSON.stringify({ module: 'announcement', action: 'create', audience, title, body })
  });

  if (res.ok) {
    await themeAlert("Broadcast Published", "Your announcement has been broadcast to the selected audience.", true);
    window.location.reload();
  } else {
    await themeAlert("Broadcast Failed", "Failed to publish broadcast.", false);
  }
};

window.deleteAnnouncement = async function(id) {
  const isSure = await themeConfirm("Delete Broadcast", "Are you sure you want to delete this broadcast from the database?");
  if (!isSure) return;
  const res = await fetch('/api/accounts/admin/portal-action/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRFToken() },
    body: JSON.stringify({ module: 'announcement', action: 'delete', id: id })
  });
  if (res.ok) {
    const card = document.getElementById(`broadcast-card-${id}`);
    if (card) card.remove();
    await themeAlert("Deleted", "Broadcast removed.", true);
  }
};

window.ADMIN_TX_CACHE = {};

async function loadLiveUserTransactions(role, accountId, targetTbodyId, colCount = 6) {
  const tbody = document.getElementById(targetTbodyId);
  if (!tbody) return;

  tbody.innerHTML = `<tr><td colspan="${colCount + 1}" class="p-4 text-center text-gray-400 text-xs">Loading live records from database...</td></tr>`;

  try {
    const res = await fetch(`/api/accounts/admin/user-transactions/${role}/${accountId}/`);
    const data = await res.json();
    const list = data.transactions || [];

    if (list.length === 0) {
      tbody.innerHTML = `<tr><td colspan="${colCount + 1}" class="p-4 text-center text-gray-400 text-xs">No transactions recorded for this ${role.toLowerCase()} yet.</td></tr>`;
      return;
    }

    tbody.innerHTML = list.map(tx => {
      window.ADMIN_TX_CACHE[tx.id] = tx;
      if (colCount === 5) {
        return `
          <tr class="hover:bg-gray-50/80">
            <td class="p-3 font-bold text-gray-700">${tx.id}</td>
            <td class="p-3 font-bold text-[#1B4D3E]">${tx.establishment}</td>
            <td class="p-3 text-gray-600">${tx.title} (${tx.amount})</td>
            <td class="p-3 text-gray-500">${tx.date}</td>
            <td class="p-3"><span class="bg-emerald-500 text-white px-2.5 py-0.5 rounded-full text-[10px] font-bold">${tx.status}</span></td>
          </tr>
        `;
      }
      return `
        <tr class="hover:bg-gray-50/80">
          <td class="p-3 font-bold text-gray-700">${tx.id}</td>
          <td class="p-3 font-bold text-[#1B4D3E]">${tx.title}</td>
          <td class="p-3 text-gray-600">${role === 'Consumer' ? tx.establishment : tx.buyer}</td>
          <td class="p-3 text-gray-500">${tx.date}</td>
          <td class="p-3 font-bold text-gray-800">${tx.total_value || tx.amount}</td>
          <td class="p-3"><span class="bg-emerald-500 text-white px-2.5 py-0.5 rounded-full text-[10px] font-bold">${tx.status}</span></td>
          <td class="p-3">
            <button type="button" onclick="openAdminTxSummaryModal('${tx.id}')" class="bg-[#1B4D3E] hover:bg-[#3A826D] text-white font-black text-[10px] px-3 py-1.5 rounded-xl shadow-xs">
              VIEW
            </button>
          </td>
        </tr>
      `;
    }).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="${colCount + 1}" class="p-4 text-center text-gray-400 text-xs">No transaction records found.</td></tr>`;
  }
}

window.openAdminTxSummaryModal = function(txId) {
  const tx = window.ADMIN_TX_CACHE[txId];
  if (!tx) return;

  document.getElementById('txSumTitle').textContent = `Transaction Summary — ${tx.id}`;
  document.getElementById('txSumSubtitle').textContent = `Status: ${tx.status}`;
  document.getElementById('txSumBuyer').textContent = tx.buyer || 'Verified Consumer';
  document.getElementById('txSumMerchant').textContent = `${tx.establishment || 'Merchant'} (${tx.address || 'Cebu City'})`;
  document.getElementById('txSumDate').textContent = tx.date || 'N/A';
  document.getElementById('txSumDeadline').textContent = tx.pickup_deadline || 'Standard Window';
  document.getElementById('txSumTotal').textContent = tx.total_value || tx.amount || '₱0.00';
  document.getElementById('txSumDeposit').textContent = tx.deposit_paid || 'Paid Online';
  document.getElementById('txSumRemaining').textContent = tx.remaining_balance || '₱0.00';

  const itemsContainer = document.getElementById('txSumItemsList');
  const items = tx.items_breakdown || [{ name: tx.title, qty: 1, unit_price: tx.amount, subtotal: tx.amount }];
  itemsContainer.innerHTML = items.map(it => `
    <div class="flex justify-between items-center bg-gray-50 px-3 py-2 rounded-xl border border-gray-100">
      <div>
        <span class="font-bold text-[#1B4D3E]">${it.qty}x ${it.name}</span>
        <span class="text-[10px] text-gray-400 block">Unit Price: ${it.unit_price}</span>
      </div>
      <span class="font-black text-gray-800">${it.subtotal}</span>
    </div>
  `).join('');

  window.openModal('adminTxSummaryModal');
};

window.toggleSeeAllMerchants = function() {
  const extraCards = document.querySelectorAll('.extra-merchant-card');
  const btn = document.getElementById('toggleAllMerchantsBtn');
  if (!extraCards.length || !btn) return;

  const isCurrentlyHidden = extraCards[0].classList.contains('hidden');
  extraCards.forEach(card => {
    if (isCurrentlyHidden) card.classList.remove('hidden');
    else card.classList.add('hidden');
  });
  btn.textContent = isCurrentlyHidden
    ? 'Show Less'
    : `See All (${document.querySelectorAll('.merchant-dir-card').length})`;
};

window.openFoodDetailModal = function(btn) {
  document.getElementById('currentFoodRawId').value = btn.dataset.rawId || '';
  document.getElementById('currentFoodRowId').value = `row-${btn.dataset.id}`;
  document.getElementById('foodModalTitle').textContent = btn.dataset.title || 'Food Item';
  document.getElementById('foodModalDesc').textContent = btn.dataset.desc || '';
  document.getElementById('foodModalQty').textContent = btn.dataset.qty || '1';
  document.getElementById('foodModalOrigPrice').textContent = btn.dataset.orig || '₱0.00';
  document.getElementById('foodModalDiscPrice').textContent = btn.dataset.disc || '₱0.00';
  if (document.getElementById('foodModalDate')) {
    document.getElementById('foodModalDate').textContent = btn.dataset.date || 'N/A';
  }
  document.getElementById('foodModalExpiry').textContent = btn.dataset.expiry || 'N/A';
  document.getElementById('foodModalMerchant').textContent = btn.dataset.merchant || 'Merchant';
  document.getElementById('foodModalAddress').textContent = btn.dataset.address || 'Cebu City';

  const imgEl = document.getElementById('foodModalImg');
  if (imgEl) {
    imgEl.src = btn.dataset.img || 'https://images.unsplash.com/photo-1509440159596-0249088772ff?auto=format&fit=crop&w=400&q=80';
  }
  window.openModal('foodModal');
};

window.openMerchantDirectoryProfile = function(cardEl) {
  const merchId = cardEl.dataset.id;
  const name = cardEl.dataset.name || 'Merchant';
  document.getElementById('mpModalInitial').textContent = name.charAt(0).toUpperCase();
  document.getElementById('mpModalName').textContent = name;
  document.getElementById('mpModalRatingBadge').textContent = `★ ${cardEl.dataset.rating || '5.0'} (${cardEl.dataset.reviews || '0'} reviews)`;
  document.getElementById('mpModalSub').textContent = `${cardEl.dataset.idLabel} • ${cardEl.dataset.type} • ${cardEl.dataset.status}`;
  document.getElementById('mpModalContact').textContent = `Contact: ${cardEl.dataset.contact}`;
  document.getElementById('mpModalPhone').textContent = `Phone: ${cardEl.dataset.phone} | Hotline: ${cardEl.dataset.hotline}`;
  document.getElementById('mpModalEmail').textContent = cardEl.dataset.email;
  document.getElementById('mpModalAddress').textContent = cardEl.dataset.address;
  document.getElementById('mpModalWallet').textContent = cardEl.dataset.wallet;
  document.getElementById('mpModalPlan').textContent = cardEl.dataset.plan;
  document.getElementById('mpModalExpiry').textContent = cardEl.dataset.expiry;
  document.getElementById('mpModalActiveCount').textContent = cardEl.dataset.active || '0';
  document.getElementById('mpModalFlaggedCount').textContent = cardEl.dataset.flagged || '0';

  const filterBtn = document.getElementById('mpFilterPageBtn');
  if (filterBtn) {
    filterBtn.onclick = () => {
      window.location.href = `/food-listing/?merchant=MID-${merchId}`;
    };
  }

  let items = [];
  try {
    items = JSON.parse(cardEl.dataset.items || '[]');
  } catch (e) {
    items = [];
  }

  const listTbody = document.getElementById('mpModalListingsBody');
  if (listTbody) {
    if (items.length === 0) {
      listTbody.innerHTML = `<tr><td colspan="6" class="p-3 text-center text-gray-400">No food listings posted by this merchant yet.</td></tr>`;
    } else {
      listTbody.innerHTML = items.map(it => {
        const photoUrl = it.image_url || 'https://images.unsplash.com/photo-1509440159596-0249088772ff?auto=format&fit=crop&w=200&q=80';
        return `
        <tr class="hover:bg-gray-50">
          <td class="p-2.5 font-bold text-gray-600">${it.id}</td>
          <td class="p-2.5">
            <div class="flex items-center gap-2.5">
              <img src="${photoUrl}" onerror="this.src='https://images.unsplash.com/photo-1509440159596-0249088772ff?auto=format&fit=crop&w=200&q=80'" class="w-9 h-9 rounded-lg object-cover border border-gray-200 shrink-0">
              <span class="font-bold text-[#1B4D3E]">${it.title}</span>
            </div>
          </td>
          <td class="p-2.5"><span class="line-through text-gray-400 text-[10px] mr-1">${it.orig_price}</span><strong>${it.disc_price}</strong></td>
          <td class="p-2.5 font-bold">${it.quantity}</td>
          <td class="p-2.5 text-gray-600">${it.expiry}</td>
          <td class="p-2.5"><span class="px-2.5 py-0.5 rounded-full text-[10px] font-bold text-white ${it.bucket === 'active' ? 'bg-emerald-500' : 'bg-rose-500'}">${it.status}</span></td>
        </tr>
      `}).join('');
    }
  }

  loadLiveUserTransactions('Merchant', merchId, 'mpModalTransactionsBody', 6);
  window.openModal('merchantDirectoryProfileModal');
};

// Update Visit Profile links in openActiveModal & openFoodBankModal to auto-open target profile
const _baseOpenActiveModal = window.openActiveModal;
window.openActiveModal = function(btn) {
  _baseOpenActiveModal(btn);
  const merchantId = btn.dataset.id;
  const visitBtn = document.getElementById('activeVisitProfileBtn');
  if (visitBtn) {
    visitBtn.onclick = () => {
      window.location.href = `/food-listing/?merchant=MID-${merchantId}&open_profile=1`;
    };
  }
};

document.addEventListener('DOMContentLoaded', () => {
  const params = new URLSearchParams(window.location.search);
  const merchParam = (params.get('merchant') || '').replace('MID-', '').trim();
  if (merchParam && params.get('open_profile') === '1') {
    const targetCard = document.getElementById(`merchant-profile-card-${merchParam}`);
    if (targetCard) {
      targetCard.classList.remove('hidden');
      setTimeout(() => window.openMerchantDirectoryProfile(targetCard), 150);
    }
  }
});