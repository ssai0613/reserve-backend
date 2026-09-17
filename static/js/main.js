/**
 * ReServe Admin Web Portal - Master JS Controller (Unified SaaS Edition)
 */

document.addEventListener('DOMContentLoaded', () => {
  if (window.lucide) {
    window.lucide.createIcons();
  }

  initDashboardCharts();
  setupGlobalListeners();
  initCalendarPickers();
});

// Re-scans the DOM for dynamic Lucide icons
function updateTable() {
  if (window.lucide) {
    window.lucide.createIcons();
  }
}

// ================= 1. UNIVERSAL MODAL SYSTEM =================
window.openModal = function(modalId) {
  const modal = document.getElementById(modalId);
  if (!modal) {
    console.warn(`Modal element with ID "${modalId}" not found.`);
    return;
  }

  modal.classList.remove('hidden');
  modal.classList.add('flex');
  document.body.classList.add('overflow-hidden');

  if (window.lucide) {
    window.lucide.createIcons();
  }
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

// ================= 2. CALENDAR PICKER INITIALIZATION =================
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
  const visibleTable = document.querySelector('table:not(.hidden)');
  if (!visibleTable) return;

  const rows = visibleTable.querySelectorAll('tbody tr');
  let matchCount = 0;
  endDate.setHours(23, 59, 59);

  rows.forEach(row => {
    const dateText = row.children[3]?.textContent.trim() || row.children[2]?.textContent.trim() || row.children[4]?.textContent.trim();
    const rowDate = new Date(dateText);

    if (!isNaN(rowDate)) {
      if (rowDate >= startDate && rowDate <= endDate) {
        row.style.display = '';
        matchCount++;
      } else {
        row.style.display = 'none';
      }
    }
  });

  alert(`Date Filter Applied: Found ${matchCount} matching records.`);
};

window.clearCalendarFilter = function() {
  const pickerInput = document.querySelector('.date-range-picker');
  if (pickerInput && pickerInput._flatpickr) {
    pickerInput._flatpickr.clear();
  }

  const visibleTable = document.querySelector('table:not(.hidden)');
  if (!visibleTable) return;

  const rows = visibleTable.querySelectorAll('tbody tr');
  rows.forEach(row => row.style.display = '');
};

// ================= 3. SORT BY CRITERIA =================
window.triggerSortByCriteria = function(selectElement) {
  const criteria = selectElement.value;
  const visibleTable = document.querySelector('table:not(.hidden)');
  if (!visibleTable || !criteria) return;

  const tbody = visibleTable.querySelector('tbody');
  const rows = Array.from(tbody.querySelectorAll('tr'));

  let colIndex = criteria.includes('name') || criteria.includes('item') ? 1 : 3;
  const isAscending = !criteria.includes('desc');

  rows.sort((a, b) => {
    let cellA = a.children[colIndex]?.textContent.trim().toLowerCase() || '';
    let cellB = b.children[colIndex]?.textContent.trim().toLowerCase() || '';

    if (criteria.includes('date')) {
      const dateA = new Date(cellA);
      const dateB = new Date(cellB);
      if (!isNaN(dateA) && !isNaN(dateB)) {
        return isAscending ? dateA - dateB : dateB - dateA;
      }
    }

    return isAscending ? cellA.localeCompare(cellB) : cellB.localeCompare(cellA);
  });

  rows.forEach(row => tbody.appendChild(row));
};

// ================= 4. GLOBAL DROPDOWN & MODAL LISTENERS =================
function setupGlobalListeners() {
  window.addEventListener('click', (event) => {
    // Backdrop click closer
    if (event.target.classList.contains('modal-overlay') || event.target.classList.contains('modal-backdrop') || event.target.hasAttribute('data-modal-container')) {
      event.target.classList.add('hidden');
      event.target.classList.remove('flex');
      document.body.classList.remove('overflow-hidden');
    }

    const notifBtn = document.getElementById('notifMenuBtn');
    const notifDropdown = document.getElementById('notifDropdown');
    if (notifBtn && notifDropdown && !notifBtn.contains(event.target) && !notifDropdown.contains(event.target)) {
      notifDropdown.classList.add('hidden');
    }

    const adminBtn = document.getElementById('adminMenuBtn');
    const adminDropdown = document.getElementById('adminDropdown');
    if (adminBtn && adminDropdown && !adminBtn.contains(event.target) && !adminDropdown.contains(event.target)) {
      adminDropdown.classList.add('hidden');
    }
  });

  const searchInputs = document.querySelectorAll('input[placeholder*="Search"]');
  searchInputs.forEach(input => {
    input.addEventListener('input', handleLiveSearch);
  });
}

window.toggleNotifMenu = function() {
  const dropdown = document.getElementById('notifDropdown');
  if (dropdown) {
    dropdown.classList.toggle('hidden');
    const badge = document.getElementById('notifBadge');
    if (badge) badge.classList.add('hidden');
  }
};

window.toggleAdminMenu = function() {
  const dropdown = document.getElementById('adminDropdown');
  if (dropdown) dropdown.classList.toggle('hidden');
};

window.openAdminProfile = function() {
  const adminDropdown = document.getElementById('adminDropdown');
  if (adminDropdown) adminDropdown.classList.add('hidden');
  window.openModal('adminProfileModal');
};

window.handleLogout = function() {

    if (confirm("Are you sure you want to log out of ReServe Admin Portal?")) {

        alert("Logged out successfully!");

        console.log("BEFORE REDIRECT:", window.location.href);

        window.location.href = "/login/";

        console.log("AFTER REDIRECT:", window.location.href);
    }

};

function togglePw() {
    const pw = document.getElementById("pw");
    const eyeIcon = document.getElementById("eyeIcon");

    if (!pw || !eyeIcon) return;

    if (pw.type === "password") {
        pw.type = "text";
        eyeIcon.setAttribute("data-lucide", "eye-off");
    } else {
        pw.type = "password";
        eyeIcon.setAttribute("data-lucide", "eye");
    }

    if (window.lucide) {
        lucide.createIcons();
    }
}

window.toggleMobileNav = function() {
  const nav = document.getElementById('mainNavbar');
  if (nav) {
    nav.classList.toggle('hidden');
    nav.classList.toggle('flex');
  }
};

// ================= 5. USER ROLE TAB SWITCHER & USER HISTORY =================
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
  }
};

window.openUserHistory = function(title, user, roleType) {
  const titleEl = document.getElementById('historyModalTitle');
  const userEl = document.getElementById('historyModalUser');
  const container = document.getElementById('historyListContainer');

  if (titleEl) titleEl.textContent = title;
  if (userEl) userEl.textContent = user;

  let items = [];
  if (roleType === 'consumer') {
    items = [
      'Acquired Produce Listing: Assorted Apples',
      'Completed Pickup: Carbon Market Outlet',
      'Added Review: ⭐⭐⭐⭐⭐',
      'Acquired Produce Listing: Native Tomatoes',
      'Updated Contact Details'
    ];
  } else if (roleType === 'foodbank') {
    items = [
      'Received Surplus Allocation: 50kg Squash',
      'Completed Intake Distribution: 100 Families',
      'Submitted Distribution Verification Report',
      'Requested Surplus Match: Fresh Veggie Hubs',
      'Updated Emergency Contact Protocol'
    ];
  } else {
    items = [
      'Posted Produce Listing: Fresh Eggplants',
      'Posted Produce Listing: Cabbage Bundle',
      'Completed Order Fulfillment: #ORD-982',
      'Initiated Payout Withdrawal: ₱10,000.00',
      'Posted Produce Listing: Local Carrots'
    ];
  }

  if (container) {
    container.innerHTML = items.map((item, idx) => `
      <div class="${idx % 2 === 0 ? 'bg-[#D2E7DD]' : 'bg-white'} px-4 py-2.5 flex items-center gap-6">
        <span class="w-24 text-gray-700 font-semibold shrink-0">2026-08-20</span>
        <span class="text-gray-900 font-medium">${item}</span>
      </div>
    `).join('');
  }

  window.openModal('userHistoryModal');
};

// ================= 6. FOOD LISTING ACTIONS =================
window.currentViewingListingId = 'FL-101';

window.openFoodDetailModal = function(listingId) {
  window.currentViewingListingId = listingId;
  const row = document.getElementById(`row-${listingId}`);
  if (row) {
    const itemName = row.querySelector('td:nth-child(2) span')?.textContent || 'Produce Item';
    const merchantName = row.querySelector('td:nth-child(3)')?.textContent || 'Merchant';
    
    const titleEl = document.getElementById('foodModalTitle');
    const merchantEl = document.getElementById('foodModalMerchant');
    if (titleEl) titleEl.textContent = itemName;
    if (merchantEl) merchantEl.textContent = merchantName;
  }
  window.openModal('foodModal');
};

window.flagFoodListing = function(listingId) {
  const targetId = listingId || window.currentViewingListingId;
  const row = document.getElementById(`row-${targetId}`);
  
  if (row) {
    const flagIcon = row.querySelector('.listing-flag-icon');
    if (flagIcon) {
      flagIcon.classList.remove('text-gray-300');
      flagIcon.classList.add('text-amber-500', 'fill-amber-500');
    }

    const statusCell = row.querySelector('.status-cell');
    if (statusCell) {
      statusCell.innerHTML = `<span class="bg-amber-500 text-white px-3 py-1 rounded-full text-[10px] font-bold">Flagged</span>`;
    }
  }

  window.closeModal('foodModal');
};

window.removeFoodListing = function(btn) {
  if (confirm("Forcibly remove this listing from consumer discovery feeds?")) {
    const row = btn.closest('tr');
    if (row) row.remove();
    alert("Listing removed successfully!");
  }
};

window.removeFoodListingById = function(listingId) {
  const targetId = listingId || window.currentViewingListingId;
  if (confirm(`Forcibly remove listing ${targetId} from consumer discovery feeds?`)) {
    const row = document.getElementById(`row-${targetId}`);
    if (row) row.remove();
    window.closeModal('foodModal');
    alert("Listing removed successfully!");
  }
};

// ================= 7. DONATION HUB WORKFLOWS =================
window.openDonationPostingModal = function(hub, items, vol, date, beneficiaries, addr, rowId) {
  const titleEl = document.getElementById('modalPostingHubTitle');
  const typeEl = document.getElementById('modalProduceType');
  const volEl = document.getElementById('modalIntakeVol');
  const benEl = document.getElementById('modalBeneficiaries');
  const addrEl = document.getElementById('modalHubAddr');
  const dateEl = document.getElementById('modalSubDate');

  if (titleEl) titleEl.textContent = hub;
  if (typeEl) typeEl.textContent = items;
  if (volEl) volEl.textContent = vol;
  if (benEl) benEl.textContent = beneficiaries;
  if (addrEl) addrEl.textContent = addr;
  if (dateEl) dateEl.textContent = date;

  const approveBtn = document.getElementById('modalApproveReqBtn');
  if (approveBtn) {
    approveBtn.onclick = function() {
      approveDonationRequest(rowId, hub);
      window.closeModal('donationPostingModal');
    };
  }

  window.openModal('donationPostingModal');
};

window.approveDonationRequest = function(rowId, hubName) {
  const row = document.getElementById(rowId);
  if (row) {
    const statusCell = row.querySelector('.status-cell');
    if (statusCell) {
      statusCell.innerHTML = `<span class="bg-emerald-500 text-white px-3 py-1 rounded-full text-[10px] font-bold">Approved</span>`;
    }
  }
  alert(`Intake request for "${hubName}" has been APPROVED and added to the dispatch queue.`);
};

window.rejectDonationRequest = function(rowId, hubName) {
  const reason = prompt(`Enter rejection reason for "${hubName}":`, "Capacity full or non-matching produce");
  if (reason) {
    const row = document.getElementById(rowId);
    if (row) row.remove();
    alert(`Intake request for "${hubName}" has been removed.`);
  }
};

window.openDonationTransactionModal = function(txId, merchant, hub, items, date, courier, status) {
  const idEl = document.getElementById('modalTxId');
  const merchantEl = document.getElementById('modalTxMerchant');
  const hubEl = document.getElementById('modalTxHub');
  const itemsEl = document.getElementById('modalTxItems');
  const dateEl = document.getElementById('modalTxDate');
  const courierEl = document.getElementById('modalTxCourier');
  const statusEl = document.getElementById('modalTxStatus');

  if (idEl) idEl.textContent = txId;
  if (merchantEl) merchantEl.textContent = merchant;
  if (hubEl) hubEl.textContent = hub;
  if (itemsEl) itemsEl.textContent = items;
  if (dateEl) dateEl.textContent = date;
  if (courierEl) courierEl.textContent = courier;
  if (statusEl) statusEl.textContent = status;

  const deliveredBtn = document.getElementById('modalDeliveredBtn');
  if (deliveredBtn) {
    deliveredBtn.onclick = function() {
      markDonationDelivered(txId);
      window.closeModal('donationTxModal');
    };
  }

  window.openModal('donationTxModal');
};

window.markDonationDelivered = function(txId) {
  const row = document.getElementById(`tx-row-${txId}`);
  if (row) {
    const statusCell = row.querySelector('.tx-status-cell');
    if (statusCell) {
      statusCell.innerHTML = `<span class="bg-emerald-500 text-white px-3 py-1 rounded-full text-[10px] font-bold">Delivered</span>`;
    }
  }
  alert(`Transaction ${txId} confirmed: Surplus received and logged.`);
};

window.flagDonationTransaction = function(txId) {
  const row = document.getElementById(`tx-row-${txId}`);
  if (row) {
    const statusCell = row.querySelector('.tx-status-cell');
    if (statusCell) {
      statusCell.innerHTML = `<span class="bg-amber-500 text-white px-3 py-1 rounded-full text-[10px] font-bold">Flagged (Delay/Issue)</span>`;
    }
  }
  alert(`Transaction ${txId} FLAGGED for logistics investigation.`);
};

// ================= 8. LIVE SEARCH, USER APPROVALS & PAYOUTS =================
function handleLiveSearch(event) {
  const query = event.target.value.toLowerCase();
  const visibleTable = document.querySelector('table:not(.hidden)');
  if (!visibleTable) return;

  const rows = visibleTable.querySelectorAll('tbody tr');
  rows.forEach(row => {
    row.style.display = row.textContent.toLowerCase().includes(query) ? '' : 'none';
  });
}

window.toggleSelectAll = function(masterCheckbox) {
  const visibleTable = document.querySelector('table:not(.hidden)');
  if (!visibleTable) return;

  const checkboxes = visibleTable.querySelectorAll('tbody input[type="checkbox"]');
  checkboxes.forEach(cb => cb.checked = masterCheckbox.checked);
};

window.approveMerchantKYB = function(accountId) {
  alert(`Account ${accountId} APPROVED! Legal documents verified.`);
  const activeBadge = document.querySelector('#table-merchant tr span') || document.querySelector('#table-foodbank tr span');
  if (activeBadge) {
    activeBadge.className = "bg-emerald-500 text-white px-3 py-1 rounded-full text-[10px] font-bold";
    activeBadge.textContent = "Active";
  }
  window.closeModal('merchantEditModal');
  window.closeModal('foodBankEditModal');
};

window.rejectMerchantKYB = function(accountId) {
  const reason = prompt("Enter rejection reason:", "Incomplete legal document submission");
  if (reason) {
    alert(`Account ${accountId} REJECTED.`);
    window.closeModal('merchantEditModal');
    window.closeModal('foodBankEditModal');
  }
};

window.approvePayout = function(btn, requestId) {
  if (confirm(`Approve GCash payout transfer for ${requestId}?`)) {
    const row = btn.closest('tr');
    if (row) {
      const statusCell = row.querySelector('td:nth-child(6) span');
      if (statusCell) {
        statusCell.className = "bg-emerald-500 text-white px-3 py-1 rounded-full font-bold";
        statusCell.textContent = "Successful";
      }
    }
    alert(`Payout ${requestId} approved! Digital ledger updated.`);
  }
};

window.rejectPayout = function(btn, requestId) {
  if (confirm(`Reject payout request ${requestId}?`)) {
    const row = btn.closest('tr');
    if (row) {
      const statusCell = row.querySelector('td:nth-child(6) span');
      if (statusCell) {
        statusCell.className = "bg-rose-500 text-white px-3 py-1 rounded-full font-bold";
        statusCell.textContent = "Rejected";
      }
    }
  }
};

window.deleteDonationRow = function(btnElement, hubName) {
  if (confirm(`Are you sure you want to delete the record for "${hubName}"?`)) {
    const row = btnElement.closest('tr');
    if (row) {
      row.remove();
      alert(`Record for "${hubName}" deleted.`);
    }
  }
};

window.handleAnnouncementSubmit = function(event) {
  event.preventDefault();
  const audience = document.getElementById('announcementAudience')?.value;
  const title = document.getElementById('announcementTitle')?.value;
  const body = document.getElementById('announcementBody')?.value;

  if (!title || !body) {
    alert('Please fill out all fields.');
    return;
  }

  const historyContainer = document.getElementById('announcementHistoryList');
  if (historyContainer) {
    const newCard = document.createElement('div');
    newCard.className = 'border border-gray-100 p-4 rounded-2xl bg-white flex justify-between items-start shadow-sm hover:shadow-md transition-all';
    newCard.innerHTML = `
      <div>
        <span class="text-[10px] font-black tracking-wider uppercase bg-[#8BC3A3]/30 text-[#1B4D3E] px-3 py-1 rounded-full border border-[#8BC3A3]/40">${audience}</span>
        <h5 class="font-bold text-sm text-gray-800 mt-2">${title}</h5>
        <p class="text-xs text-gray-500 mt-1 leading-relaxed">${body}</p>
        <p class="text-[10px] text-gray-400 font-medium mt-2">Posted on: ${new Date().toLocaleString()}</p>
      </div>
      <button onclick="this.parentElement.remove()" class="text-gray-400 hover:text-red-500 p-1">
        <i data-lucide="trash-2" class="w-4 h-4"></i>
      </button>
    `;
    historyContainer.prepend(newCard);
    if (window.lucide) window.lucide.createIcons();
  }

  document.getElementById('announcementTitle').value = '';
  document.getElementById('announcementBody').value = '';
  alert('Announcement broadcasted system-wide!');
};

// ================= 9. CHART.JS INITIALIZATION =================
function initDashboardCharts() {
  const mainCtx = document.getElementById('userGrowthChart')?.getContext('2d');
  if (mainCtx) {
    new Chart(mainCtx, {
      type: 'line',
      data: {
        labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug'],
        datasets: [
          {
            label: 'Surplus Rescued (kg)',
            data: [2500, 3800, 3200, 5100, 4800, 7200, 6800, 9400],
            borderColor: '#3A826D',
            backgroundColor: 'rgba(58, 130, 109, 0.12)',
            fill: true,
            tension: 0.42,
            borderWidth: 3,
            pointBackgroundColor: '#1B4D3E',
            pointRadius: 3
          },
          {
            label: 'New Consumers',
            data: [1200, 1900, 2400, 2900, 3700, 4200, 5800, 6900],
            borderColor: '#EBB338',
            backgroundColor: 'rgba(235, 179, 56, 0.08)',
            fill: true,
            tension: 0.42,
            borderWidth: 2.5,
            borderDash: [5, 5],
            pointRadius: 0
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: 'top', align: 'end', labels: { boxWidth: 10, font: { size: 11, weight: 'bold' } } }
        },
        scales: {
          x: { grid: { display: false }, ticks: { font: { size: 10 } } },
          y: { grid: { color: 'rgba(0,0,0,0.04)' }, ticks: { font: { size: 10 } } }
        }
      }
    });
  }

  const donutCtx = document.getElementById('trafficDonutChart')?.getContext('2d');
  if (donutCtx) {
    new Chart(donutCtx, {
      type: 'doughnut',
      data: {
        labels: ['Bakeries', 'Supermarkets', 'Restaurants'],
        datasets: [{
          data: [55, 33, 12],
          backgroundColor: ['#1B4D3E', '#3A826D', '#EBB338'],
          borderWidth: 0,
          hoverOffset: 4
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '72%',
        plugins: { legend: { display: false } }
      }
    });
  }
}