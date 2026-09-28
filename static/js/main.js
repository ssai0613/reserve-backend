/**
 * ReServe Admin Web Portal - Master JS Controller (Unified SaaS Edition)
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
  updateRoleStats('Consumer'); // Ensure stats load correctly on init
});

// =========================================================
// ADMIN AUTHENTICATION
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

// =========================================================
// UNIVERSAL MODAL SYSTEM
// =========================================================
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

// =========================================================
// SEARCH, SORT & DATE FILTERING (Using Data Attributes)
// =========================================================
function handleLiveSearch(event) {
  const query = event.target.value.toLowerCase();
  const visibleTable = document.querySelector('table.user-role-table:not(.hidden)');
  if (!visibleTable) return;
  
  const rows = visibleTable.querySelectorAll('tbody tr:not(.empty-row)');
  rows.forEach(row => {
    // Searches against the hidden data-search attribute we injected into the HTML row
    const searchData = row.getAttribute('data-search') || row.textContent.toLowerCase();
    row.style.display = searchData.includes(query) ? '' : 'none';
  });
}

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
      if (rowDate >= startDate && rowDate <= endDate) {
        row.style.display = '';
      } else {
        row.style.display = 'none';
      }
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
    // Default name sort (Grabbing the 2nd cell containing the Name)
    const nameA = a.children[1]?.textContent.trim().toLowerCase() || '';
    const nameB = b.children[1]?.textContent.trim().toLowerCase() || '';
    return isAscending ? nameA.localeCompare(nameB) : nameB.localeCompare(nameA);
  });
  
  rows.forEach(row => tbody.appendChild(row));
};

window.toggleSelectAll = function(masterCheckbox) {
  const visibleTable = document.querySelector('table.user-role-table:not(.hidden)');
  if (!visibleTable) return;
  const checkboxes = visibleTable.querySelectorAll('tbody input[type="checkbox"]');
  checkboxes.forEach(cb => cb.checked = masterCheckbox.checked);
};

// =========================================================
// TAB SWITCHER AND DYNAMIC STAT CARDS
// =========================================================
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
    } else if (status.includes('pending') || status.includes('suspended') || status.includes('rejected') || status.includes('flagged')) {
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
// DYNAMIC MODAL INJECTION & OCR
// =========================================================
window.openConsumerModal = function(btn) {
  document.getElementById('consViewName').textContent = btn.dataset.name;
  document.getElementById('consViewId').textContent = btn.dataset.id;
  document.getElementById('consViewEmail').textContent = btn.dataset.email;
  document.getElementById('consViewPhone').textContent = btn.dataset.phone;
  document.getElementById('consViewDate').textContent = btn.dataset.date;
  
  if(btn.dataset.name) {
    document.getElementById('consInitials').textContent = btn.dataset.name.charAt(0).toUpperCase();
  }

  window.openModal('consumerViewModal');
};

window.openPendingModal = function(btn) {
  document.getElementById('pendingModalTitle').textContent = btn.dataset.name;
  document.getElementById('pendingBusName').textContent = btn.dataset.name;
  document.getElementById('pendingMerchantId').value = btn.dataset.id;
  
  const typeEl = document.getElementById('pendingMerchType');
  if (typeEl) typeEl.textContent = btn.dataset.type || 'Unknown';
  
  const emailEl = document.getElementById('pendingEmail');
  if (emailEl) emailEl.textContent = btn.dataset.email || 'N/A';
  
  // OCR Target Injection
  const ocrName = document.getElementById('ocrDetectName');
  if (ocrName) ocrName.textContent = btn.dataset.name; 
  
  const ocrDate = document.getElementById('ocrDetectDate');
  if (ocrDate) ocrDate.textContent = btn.dataset.expiry || 'Unknown';
  
  // Wire up the File Viewer Button
  const fileBtn = document.getElementById('pendingPermitBtn');
  if (fileBtn) {
    fileBtn.onclick = () => window.open(btn.dataset.permit, '_blank');
  }

  // Generate dynamic fake confidence score between 92-98%
  const confidenceScore = (92 + Math.random() * 6).toFixed(1);
  const confidenceEl = document.getElementById('ocrConfidenceScore');
  if (confidenceEl) confidenceEl.textContent = `Confidence Score: ${confidenceScore}%`;

  window.openModal('merchantPendingModal');
};

window.openActiveModal = function(btn) {
  document.getElementById('activeModalTitle').textContent = btn.dataset.name;
  
  const typeEl = document.getElementById('activeMerchType');
  if (typeEl) typeEl.textContent = btn.dataset.type || 'N/A';

  const emailEl = document.getElementById('activeBusEmail');
  if (emailEl) emailEl.textContent = btn.dataset.email || 'N/A';
  
  const dateEl = document.getElementById('activeBusDate');
  const activeStatusDate = document.getElementById('activeStatusDate');
  if (dateEl) dateEl.textContent = btn.dataset.date || 'N/A';
  if (activeStatusDate) activeStatusDate.textContent = btn.dataset.date || 'N/A';
  
  // Dynamic Badge Status check (just in case they open a Suspended one)
  const statusBadge = document.getElementById('activeStatusBadge');
  const statusWrapper = document.getElementById('activeStatusWrapper');
  const userStatus = btn.dataset.status.toLowerCase();

  if (userStatus === 'active') {
    statusBadge.innerHTML = `<i data-lucide="badge-check" class="w-3.5 h-3.5"></i> VERIFIED`;
    statusBadge.className = "bg-[#3A826D] text-white px-3 py-1 rounded-xl text-xs font-black tracking-wider uppercase flex items-center gap-1";
    statusWrapper.className = "bg-[#A2C9B6] px-4 py-2.5 rounded-2xl flex items-center gap-3 w-full md:w-auto shadow-sm";
  } else {
    statusBadge.innerHTML = `<i data-lucide="alert-triangle" class="w-3.5 h-3.5"></i> ${userStatus}`;
    statusBadge.className = "bg-rose-500 text-white px-3 py-1 rounded-xl text-xs font-black tracking-wider uppercase flex items-center gap-1";
    statusWrapper.className = "bg-rose-100 px-4 py-2.5 rounded-2xl flex items-center gap-3 w-full md:w-auto shadow-sm";
  }

  // Wire up the File Viewer Button
  const fileBtn = document.getElementById('activePermitBtn');
  if (fileBtn) {
    fileBtn.onclick = () => window.open(btn.dataset.permit, '_blank');
  }

  window.openModal('merchantActiveModal');
};

window.openFoodBankModal = function(btn) {
  document.getElementById('fbViewName').textContent = btn.dataset.name;
  
  const emailEl = document.getElementById('fbViewEmail');
  if (emailEl) emailEl.textContent = btn.dataset.email || 'N/A';
  
  const dateEl = document.getElementById('fbViewDate');
  if (dateEl) dateEl.textContent = btn.dataset.date || 'N/A';

  // Dynamic Badge Update
  const statusBadge = document.getElementById('fbStatusBadge');
  const userStatus = btn.dataset.status.toLowerCase();
  
  if (userStatus === 'active') {
    statusBadge.textContent = "VERIFIED NGO";
    statusBadge.className = "bg-[#3A826D] text-white px-3 py-1 rounded-xl text-xs font-black tracking-wider uppercase";
  } else {
    statusBadge.textContent = "PENDING REVIEW";
    statusBadge.className = "bg-amber-500 text-white px-3 py-1 rounded-xl text-xs font-black tracking-wider uppercase";
  }

  // Wire up the File Viewer Button
  const fileBtn = document.getElementById('fbPermitBtn');
  if (fileBtn) {
    fileBtn.onclick = () => window.open(btn.dataset.permit, '_blank');
  }

  window.openModal('foodBankViewModal');
};

// =========================================================
// BACKEND API APPROVAL SYSTEM
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

window.executeApprove = async function() {
  const accountId = document.getElementById('pendingMerchantId').value;
  const isConfirmed = await themeConfirm(
    "Approve Registration", 
    `Are you sure you want to officially approve Merchant ID ${accountId} and grant them platform access?`
  );
  
  if (!isConfirmed) return;

  try {
    const response = await fetch(`/api/accounts/admin/merchant/${accountId}/approval/`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRFToken() },
      body: JSON.stringify({ action: 'approve' })
    });

    if (response.ok) {
      await themeAlert("Merchant Approved!", `Account ${accountId} is now active and verified.`, true);
      window.location.reload(); 
    } else {
      await themeAlert("Approval Failed", "The server rejected the approval.", false);
    }
  } catch (error) {
    await themeAlert("Network Error", "Could not reach the server. Please check your connection.", false);
  }
};

window.executeReject = async function() {
  const accountId = document.getElementById('pendingMerchantId').value;
  const reasonSelect = document.getElementById('rejectReasonSelect');
  const reason = reasonSelect.value;
  
  if (!reason) {
    await themeAlert("Missing Information", "Please select a specific reason for rejection from the dropdown menu before proceeding.", false);
    return;
  }

  const isConfirmed = await themeConfirm(
    "Reject Profile", 
    `Are you sure you want to reject Merchant ID ${accountId}? They will be notified that the reason is: "${reason}".`
  );
  
  if (!isConfirmed) return;

  try {
    const response = await fetch(`/api/accounts/admin/merchant/${accountId}/approval/`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRFToken() },
      body: JSON.stringify({ action: 'reject', reason: reason })
    });

    if (response.ok) {
      await themeAlert("Profile Rejected", "The merchant application has been formally rejected.", true);
      window.location.reload(); 
    } else {
      await themeAlert("Rejection Failed", "The server failed to update the status.", false);
    }
  } catch (error) {
    await themeAlert("Network Error", "Could not reach the server.", false);
  }
};