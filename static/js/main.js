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
      alert('Admin profile email updated in database!');
    } else {
      alert('Failed to update admin email.');
    }
  } catch (e) {
    alert('Network error while saving profile.');
  }
};

window.handleLogout = function() {
  localStorage.removeItem('admin_access_token');
  localStorage.removeItem('admin_refresh_token');
  window.location.href = '/login/';
};

// =========================================================
// LIVE USER TRANSACTION FETCHER
// =========================================================
async function loadLiveUserTransactions(role, accountId, targetTbodyId, colCount = 6) {
  const tbody = document.getElementById(targetTbodyId);
  if (!tbody) return;

  tbody.innerHTML = `<tr><td colspan="${colCount}" class="p-4 text-center text-gray-400 text-xs">Loading live records from database...</td></tr>`;

  try {
    const res = await fetch(`/api/accounts/admin/user-transactions/${role}/${accountId}/`);
    const data = await res.json();
    const list = data.transactions || [];

    if (list.length === 0) {
      tbody.innerHTML = `<tr><td colspan="${colCount}" class="p-4 text-center text-gray-400 text-xs">No transactions recorded for this ${role.toLowerCase()} yet.</td></tr>`;
      return;
    }

    tbody.innerHTML = list.map(tx => {
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
          <td class="p-3 font-bold text-gray-800">${tx.amount}</td>
          <td class="p-3"><span class="bg-emerald-500 text-white px-2.5 py-0.5 rounded-full text-[10px] font-bold">${tx.status}</span></td>
        </tr>
      `;
    }).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="${colCount}" class="p-4 text-center text-gray-400 text-xs">No transaction records found.</td></tr>`;
  }
}

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

window.openPendingModal = function(btn) {
  const merchantId = btn.dataset.id;
  const businessName = btn.dataset.name || 'Merchant';

  document.getElementById('pendingModalTitle').textContent = businessName;
  document.getElementById('pendingBusName').textContent = businessName;
  document.getElementById('pendingMerchType').textContent = btn.dataset.type || 'Standard';
  document.getElementById('pendingAddress').textContent = btn.dataset.address || 'Not Provided';
  document.getElementById('pendingContact').textContent = btn.dataset.contact || 'Not Provided';
  document.getElementById('pendingPhone').textContent = btn.dataset.phone || 'Not Provided';
  document.getElementById('pendingHotline').textContent = btn.dataset.hotline || 'N/A';
  document.getElementById('pendingEmail').textContent = btn.dataset.email || 'N/A';
  document.getElementById('pendingDate').textContent = btn.dataset.date || 'N/A';
  document.getElementById('pendingMerchantId').value = merchantId;

  const fileBtn = document.getElementById('pendingPermitBtn');
  if (fileBtn) {
    fileBtn.onclick = () => window.open(btn.dataset.permit || '', '_blank');
  }

  let ocrData = {};
  try {
    ocrData = JSON.parse(btn.dataset.ocr || '{}');
  } catch (e) {
    ocrData = {};
  }

  document.getElementById('ocrDetectName').value = ocrData.business_name || 'Not Detected';
  document.getElementById('ocrDetectPermitNo').value = ocrData.permit_number || 'Not Detected';
  document.getElementById('ocrDetectLGU').value = ocrData.lgu_anchor || 'Unverified';
  document.getElementById('ocrDetectAddress').value = ocrData.business_address || 'Not Detected';
  document.getElementById('ocrDetectNature').value = ocrData.nature_of_business || 'Not Detected';
  document.getElementById('ocrDetectYear').value = ocrData.calendar_year ? `Year ${ocrData.calendar_year}` : 'Not Detected';
  
  const repText = [ocrData.representative, ocrData.ownership_type].filter(Boolean).join(' • ');
  document.getElementById('ocrDetectRep').value = repText || ocrData.taxpayer_name || 'Not Detected';

  const detectedExpiry = (ocrData.expiry_date && ocrData.expiry_date !== 'Not Detected')
    ? ocrData.expiry_date
    : (btn.dataset.expiry || '');
  document.getElementById('ocrDetectExpiry').value = detectedExpiry;

  window.setOcrInputsEditable(false);

  const confidence = ocrData.confidence_score ? `${ocrData.confidence_score}%` : 'Pending/0.0%';
  const confidenceEl = document.getElementById('ocrConfidenceScore');
  if (confidenceEl) {
    confidenceEl.textContent = `Confidence: ${confidence}`;
    if (parseFloat(ocrData.confidence_score || 0) >= 85) {
      confidenceEl.className = "bg-emerald-50 text-emerald-800 font-black text-[10px] px-3 py-1 rounded-full border border-emerald-200";
    } else {
      confidenceEl.className = "bg-amber-50 text-amber-800 font-black text-[10px] px-3 py-1 rounded-full border border-amber-200";
    }
  }

  window.openModal('merchantPendingModal');
};

// =========================================================
// 3. MERCHANT VIEW MODAL (WITH LIVE TRANSACTIONS & EXPIRY)
// =========================================================
window.openActiveModal = function(btn) {
  const merchantId = btn.dataset.id;
  document.getElementById('activeMerchantId').value = merchantId;
  document.getElementById('activeModalTitle').textContent = btn.dataset.name || 'Merchant';
  document.getElementById('activeBusName').textContent = btn.dataset.name || 'N/A';
  document.getElementById('activeMerchType').textContent = btn.dataset.type || 'N/A';
  document.getElementById('activeBusAddress').textContent = btn.dataset.address || 'Not Provided';
  document.getElementById('activeContactPerson').textContent = btn.dataset.contact || 'Not Provided';
  document.getElementById('activeContactPhone').textContent = btn.dataset.phone || 'Not Provided';
  document.getElementById('activeHotline').textContent = btn.dataset.hotline || 'N/A';
  document.getElementById('activeBusEmail').textContent = btn.dataset.email || 'N/A';
  document.getElementById('activeBusDate').textContent = btn.dataset.date || 'N/A';
  document.getElementById('activeStatusDate').textContent = btn.dataset.date || 'N/A';

  const txSection = document.getElementById('merchantTransactionsSection');
  if (txSection) txSection.classList.add('hidden');

  if (merchantId) {
    loadLiveUserTransactions('Merchant', merchantId, 'merchantTransactionsBody', 6);
  }

  let ocrData = {};
  try {
    ocrData = JSON.parse(btn.dataset.ocr || '{}');
  } catch (e) {
    ocrData = {};
  }
  document.getElementById('activePermitNo').textContent = ocrData.permit_number || 'Verified on File';
  document.getElementById('activePermitLGU').textContent = ocrData.lgu_anchor || 'Cebu City LGU';

  const expiryStr = btn.dataset.expiry || '';
  document.getElementById('activePermitExpiry').textContent = expiryStr || 'N/A';
  const expiryAlert = document.getElementById('activePermitExpiryAlert');
  const expiryAlertText = document.getElementById('activePermitExpiryAlertText');

  if (expiryStr && expiryAlert) {
    const today = new Date();
    const expiryDate = new Date(expiryStr);
    const diffDays = Math.ceil((expiryDate - today) / (1000 * 60 * 60 * 24));

    if (diffDays < 0) {
      expiryAlert.classList.remove('hidden');
      expiryAlertText.textContent = `Business Permit EXPIRED on ${expiryStr} (${Math.abs(diffDays)} days ago). Request renewal immediately.`;
    } else if (diffDays <= 30) {
      expiryAlert.classList.remove('hidden');
      expiryAlertText.textContent = `Business Permit expires in ${diffDays} days (${expiryStr}). Notify merchant to submit renewed permit.`;
    } else {
      expiryAlert.classList.add('hidden');
    }
  }

  const statusBadge = document.getElementById('activeStatusBadge');
  const statusWrapper = document.getElementById('activeStatusWrapper');
  const userStatus = (btn.dataset.status || 'Active').toLowerCase();

  if (userStatus === 'active') {
    statusBadge.innerHTML = `<i data-lucide="badge-check" class="w-3.5 h-3.5"></i> VERIFIED`;
    statusBadge.className = "bg-[#3A826D] text-white px-3 py-1 rounded-xl text-xs font-black tracking-wider uppercase flex items-center gap-1";
    statusWrapper.className = "bg-[#A2C9B6] px-4 py-2.5 rounded-2xl flex items-center gap-3 w-full md:w-auto shadow-sm";
  } else {
    statusBadge.innerHTML = `<i data-lucide="alert-triangle" class="w-3.5 h-3.5"></i> ${btn.dataset.status}`;
    statusBadge.className = "bg-rose-500 text-white px-3 py-1 rounded-xl text-xs font-black tracking-wider uppercase flex items-center gap-1";
    statusWrapper.className = "bg-rose-100 px-4 py-2.5 rounded-2xl flex items-center gap-3 w-full md:w-auto shadow-sm";
  }

  const fileBtn = document.getElementById('activePermitBtn');
  if (fileBtn) {
    fileBtn.onclick = () => window.open(btn.dataset.permit, '_blank');
  }

  const visitBtn = document.getElementById('activeVisitProfileBtn');
  if (visitBtn) {
    visitBtn.onclick = () => {
      window.location.href = `/food-listing/?merchant=MID-${merchantId}`;
    };
  }

  window.openModal('merchantActiveModal');
};

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

window.openFoodBankModal = function(btn) {
  const fbId = btn.dataset.id;
  document.getElementById('activeFoodBankId').value = fbId;
  document.getElementById('fbViewName').textContent = btn.dataset.name || 'Organization';
  document.getElementById('fbViewAddress').textContent = btn.dataset.address || 'Not Provided';
  document.getElementById('fbViewContact').textContent = btn.dataset.contact || 'Not Provided';
  document.getElementById('fbViewPhone').textContent = btn.dataset.phone || 'Not Provided';
  document.getElementById('fbViewHotline').textContent = btn.dataset.hotline || 'N/A';
  document.getElementById('fbViewEmail').textContent = btn.dataset.email || 'N/A';
  document.getElementById('fbViewDate').textContent = btn.dataset.date || 'N/A';
  document.getElementById('fbViewExpiry').textContent = btn.dataset.expiry || 'N/A';

  const txSection = document.getElementById('fbTransactionsSection');
  if (txSection) txSection.classList.add('hidden');

  if (fbId) {
    loadLiveUserTransactions('FoodBank', fbId, 'fbTransactionsBody', 5);
  }

  const statusBadge = document.getElementById('fbStatusBadge');
  const userStatus = (btn.dataset.status || 'Active').toLowerCase();
  
  if (userStatus === 'active') {
    statusBadge.textContent = "VERIFIED NGO";
    statusBadge.className = "bg-[#3A826D] text-white px-3 py-1 rounded-xl text-xs font-black tracking-wider uppercase";
  } else {
    statusBadge.textContent = btn.dataset.status.toUpperCase();
    statusBadge.className = "bg-rose-500 text-white px-3 py-1 rounded-xl text-xs font-black tracking-wider uppercase";
  }

  const fileBtn = document.getElementById('fbPermitBtn');
  if (fileBtn) {
    fileBtn.onclick = () => window.open(btn.dataset.permit, '_blank');
  }

  const visitBtn = document.getElementById('fbVisitProfileBtn');
  if (visitBtn) {
    visitBtn.onclick = () => {
      window.location.href = `/donations/?foodbank=FB-${fbId}`;
    };
  }

  window.openModal('foodBankViewModal');
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

window.openFoodDetailModal = function(btn) {
  document.getElementById('currentFoodRawId').value = btn.dataset.rawId || '';
  document.getElementById('currentFoodRowId').value = `row-${btn.dataset.id}`;
  document.getElementById('foodModalTitle').textContent = btn.dataset.title || 'Food Item';
  document.getElementById('foodModalDesc').textContent = btn.dataset.desc || '';
  document.getElementById('foodModalQty').textContent = btn.dataset.qty || '1';
  document.getElementById('foodModalOrigPrice').textContent = btn.dataset.orig || '₱0.00';
  document.getElementById('foodModalDiscPrice').textContent = btn.dataset.disc || '₱0.00';
  document.getElementById('foodModalDate').textContent = btn.dataset.date || 'N/A';
  document.getElementById('foodModalExpiry').textContent = btn.dataset.expiry || 'N/A';
  document.getElementById('foodModalMerchant').textContent = btn.dataset.merchant || 'Merchant';
  document.getElementById('foodModalAddress').textContent = btn.dataset.address || 'Cebu City';
  window.openModal('foodModal');
};

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

window.removeFoodListing = async function(rawId, rowId) {
  if (!confirm("Are you sure you want to remove this food listing from the database?")) return;
  await fetch('/api/accounts/admin/portal-action/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRFToken() },
    body: JSON.stringify({ module: 'listing', action: 'delete', id: rawId })
  });
  const row = document.getElementById(rowId);
  if (row) row.remove();
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

window.handlePayoutAction = async function(action, rawId, rowId, isWallet = true) {
  if (!confirm(`Confirm ${action} for this payout request?`)) return;
  await fetch('/api/accounts/admin/portal-action/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRFToken() },
    body: JSON.stringify({ module: 'payout', action: action, id: rawId, is_merchant_wallet: isWallet })
  });
  window.location.reload();
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
    window.location.reload();
  } else {
    alert("Failed to publish broadcast.");
  }
};

window.deleteAnnouncement = async function(id) {
  if (!confirm("Delete this broadcast from the database?")) return;
  const res = await fetch('/api/accounts/admin/portal-action/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRFToken() },
    body: JSON.stringify({ module: 'announcement', action: 'delete', id: id })
  });
  if (res.ok) {
    const card = document.getElementById(`broadcast-card-${id}`);
    if (card) card.remove();
  }
};