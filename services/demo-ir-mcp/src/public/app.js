const RELATIONSHIP_FIELDS = {
  existing: [
    ['investorId', 'LP ID', 'readonly-id'],
    ['name', 'Name', 'text', { required: true, full: true }],
    ['lpType', 'LP type', 'select'],
    ['domicile', 'Domicile', 'select'],
    ['taxStatus', 'Tax status', 'select'],
    ['relationshipStatus', 'Relationship status', 'select'],
  ],
  prospect: [
    ['prospectId', 'Prospect ID', 'readonly-id'],
    ['name', 'Name', 'text', { required: true, full: true }],
    ['fundType', 'Fund type', 'select'],
    ['country', 'Country', 'select'],
    ['prospectCategory', 'Prospect category', 'select'],
    ['aumUsdBn', 'AUM (USD bn)', 'number'],
    ['priorityTier', 'Priority tier', 'select'],
    ['pipelineStage', 'Pipeline stage', 'select'],
    ['stageDetail', 'Stage detail', 'textarea', { full: true }],
    ['probabilityPct', 'Probability (%)', 'probability', { min: '0', max: '100', step: '0.1' }],
    ['targetCommitmentUsdMm', 'Target commitment (USD mm)', 'number'],
    ['weightedCommitmentUsdMm', 'Weighted commitment (USD mm)', 'number'],
    ['lastContactDate', 'Last contact date', 'date'],
    ['nextTouchpointDate', 'Next touchpoint date', 'date'],
  ],
};

const FIELD_CONFIG = {
  coverageAssignments: [
    ['coverageRole', 'Coverage role', 'select'],
    ['ownerName', 'Owner name', 'select'],
    ['team', 'Team', 'select'],
    ['assignedDate', 'Assigned date', 'date'],
  ],
  contacts: [
    ['contactId', 'Contact ID', 'readonly-id'],
    ['name', 'Name', 'text', { required: true }],
    ['title', 'Title'],
    ['email', 'Email', 'email'],
    ['phone', 'Phone', 'tel'],
    ['roleType', 'Role type', 'select'],
    ['primaryContact', 'Primary contact', 'checkbox'],
  ],
  subscriptions: [
    ['fund', 'Fund', 'select'],
    ['initialSubscriptionDate', 'Initial subscription date', 'date'],
    ['initialSubscriptionUsdMm', 'Initial subscription (USD mm)', 'number'],
    ['currentNavUsdMm', 'Current NAV (USD mm)', 'number'],
    ['cumulativeNetReturnPct', 'Cumulative net return (%)', 'number'],
    ['annualizedNetReturnPct', 'Annualized net return (%)', 'number'],
    ['highWaterMarkStatus', 'High-water mark status', 'select'],
    ['redemptionFrequency', 'Redemption frequency', 'select'],
    ['redemptionNoticeDays', 'Redemption notice (days)', 'select'],
  ],
  diligence: [
    ['ddqType', 'DDQ type', 'select'],
    ['ddqStatus', 'DDQ status', 'select'],
    ['status', 'Status', 'select'],
    ['sentDate', 'Sent date', 'date'],
    ['dueDate', 'Due date', 'date'],
    ['completedDate', 'Completed date', 'date'],
    ['lastCompletedDate', 'Last completed date', 'date'],
    ['keyFocusAreas', 'Key focus areas', 'list'],
    ['targetCompletionDate', 'Target completion date', 'date'],
    ['notes', 'Notes', 'textarea', { full: true }],
  ],
  tasks: [
    ['taskId', 'Task ID', 'readonly-id'],
    ['description', 'Description', 'textarea', { required: true, full: true }],
    ['owner', 'Owner', 'select'],
    ['dueDate', 'Due date', 'date'],
    ['priority', 'Priority', 'select'],
    ['status', 'Status', 'select'],
    ['notes', 'Notes', 'textarea', { full: true }],
  ],
  activities: [
    ['activityId', 'Activity ID', 'readonly-id'],
    ['date', 'Date', 'date'],
    ['type', 'Type', 'select'],
    ['owner', 'Owner', 'select'],
    ['contactName', 'Contact name'],
    ['subject', 'Subject'],
    ['notes', 'Notes', 'textarea', { full: true }],
    ['nextSteps', 'Next steps', 'textarea', { full: true }],
    ['location', 'Location'],
    ['attendees', 'Attendees', 'list'],
    ['outcome', 'Outcome', 'textarea', { full: true }],
  ],
  calendarEvents: [
    ['date', 'Date', 'date'],
    ['time', 'Time', 'time'],
    ['type', 'Type', 'select'],
    ['owner', 'Owner', 'select'],
    ['attendees', 'Attendees', 'list'],
    ['purpose', 'Purpose', 'textarea', { required: true, full: true }],
    ['relatedItem', 'Related item', 'textarea', { full: true }],
    ['status', 'Status', 'select'],
  ],
  messages: [
    ['from', 'From'],
    ['to', 'To', 'list'],
    ['cc', 'Cc', 'list'],
    ['subject', 'Subject', 'text', { required: true, full: true }],
    ['date', 'Date and time', 'datetime-local'],
    ['body', 'Body', 'textarea', { full: true, tall: true }],
  ],
};

const OWNER_OPTIONS = ['Claire Whitfield', 'Daniel Ferreira', 'James Okafor', 'Renata Silva'];

const OPTION_CATALOG = {
  'relationships.existing.lpType': [
    'Public Pension',
    'Foundation',
    'Insurance',
    'Family Office',
    'Endowment',
    'Fund of Funds',
    'Sovereign-Linked',
    'OCIO',
  ],
  'relationships.existing.domicile': ['US', 'UK', 'Cayman', 'Singapore'],
  'relationships.existing.taxStatus': ['Tax-Exempt', 'Taxable', 'Exempt (Non-US)'],
  'relationships.existing.relationshipStatus': [
    'Active',
    'Active - At Risk',
    'Active - Watch',
    'Active - Dormant',
  ],
  'relationships.prospect.fundType': [
    'Sovereign Wealth Fund',
    'Large Family Office',
    'Canadian Pension Fund',
    'Nordic Pension Fund',
    'Family Office',
    'Sovereign-Linked',
  ],
  'relationships.prospect.country': [
    'Australia',
    'Brazil',
    'Canada',
    'Finland',
    'Singapore',
    'Sweden',
    'UAE',
    'UK',
  ],
  'relationships.prospect.prospectCategory': ['New Logo', 'Existing Investor - Upsell'],
  'relationships.prospect.priorityTier': ['1', '2', '3'],
  'relationships.prospect.pipelineStage': [
    'Outreach Sent',
    'Meeting Scheduled',
    'In Diligence',
    'Final IC Review',
    'Documentation & Signing',
  ],
  'coverageAssignments.coverageRole': ['Primary', 'Secondary', 'Lead', 'Support'],
  'coverageAssignments.ownerName': OWNER_OPTIONS,
  'coverageAssignments.team': [
    'Institutional & Public Pensions',
    'Endowments & Foundations',
    'Insurance & Institutional',
    'Family Office & Private Wealth',
    'Fund of Funds & Consultants',
    'Sovereign & Cross-Border',
    'OCIO & Consultants',
    'Fund V Fundraising',
    'Family Office & Private Wealth (existing coverage)',
    'Sovereign & Cross-Border (existing coverage)',
  ],
  'contacts.roleType': ['Decision Maker', 'Decision Influencer', 'Operations/Compliance'],
  'subscriptions.fund': ['Fund II - Global Macro', 'Fund III - Credit'],
  'subscriptions.highWaterMarkStatus': ['Above HWM'],
  'subscriptions.redemptionFrequency': ['Quarterly', 'Semi-Annual'],
  'subscriptions.redemptionNoticeDays': ['45', '90'],
  'diligence.ddqType': ['Annual ODD Renewal', 'Supplemental DDQ (Regulatory Exam)'],
  'diligence.existing.status': [
    'Not Yet Due',
    'Open - In Progress',
    'Open - Due Today',
    'Overdue - No Response',
    'Completed',
  ],
  'diligence.prospect.ddqStatus': [
    'In Progress',
    'In Progress - Quantitative Screen',
    'Passed',
    'Passed - Advancing to Documentation',
    'Passed - In Documentation Phase',
    'Passed Screening - Full DDQ Not Yet Started',
    'Passed - IC Cleared, Final Presentation Prep',
    'N/A - Existing Relationship',
  ],
  'tasks.owner': OWNER_OPTIONS,
  'tasks.priority': ['LOW', 'MEDIUM', 'HIGH', 'URGENT'],
  'tasks.status': ['Open', 'Overdue', 'Completed'],
  'activities.owner': OWNER_OPTIONS,
  'activities.type': [
    'Ad Hoc Email',
    'Annual Meeting Invite Sent',
    'Call',
    'Call Attempted',
    'Conference Introduction',
    'Conference Meeting',
    'DDQ Received',
    'DDQ Sent',
    'Deliverable Sent',
    'Email',
    'In-Person Meeting',
    'Internal Note',
    'K-1 Delivered',
    'Legal Document',
    'Meeting',
    'NAV Statement Sent',
    'Performance Fee Crystallization Notice',
    'Quarterly Call',
    'Reference Call',
    'Task',
    'Video Call',
  ],
  'calendarEvents.owner': OWNER_OPTIONS,
  'calendarEvents.type': [
    'Call',
    'Conference / Investor Day',
    'Deliverable / Email',
    'Email',
    'IC Presentation',
    'In-Person Meeting (Executive)',
    'Milestone (no call)',
    'Quarterly Call',
    'Site Visit',
  ],
  'calendarEvents.status': [
    'Awaiting external action',
    'Blocked - materials not yet sent',
    'Confirmed',
    'Planned',
    'Proposed - awaiting confirmation',
    'Proposed - provisional',
    'Save-the-date sent',
    'Tentative - contact unresponsive',
  ],
};

const RESOURCE_META = {
  coverageAssignments: { label: 'Coverage', singular: 'coverage assignment' },
  contacts: { label: 'Contacts', singular: 'contact' },
  subscriptions: { label: 'Subscriptions', singular: 'subscription' },
  diligence: { label: 'Diligence', singular: 'diligence record' },
  tasks: { label: 'Tasks', singular: 'task' },
  activities: { label: 'Activities', singular: 'activity' },
  calendarEvents: { label: 'Meetings', singular: 'meeting' },
  messages: { label: 'Emails', singular: 'email' },
};

const RELATED_RESOURCES = [
  'coverageAssignments',
  'contacts',
  'subscriptions',
  'diligence',
  'tasks',
  'activities',
  'calendarEvents',
  'messages',
];

const RELATED_COLUMNS = {
  coverageAssignments: [
    ['ownerName', 'Owner'],
    ['coverageRole', 'Role'],
    ['team', 'Team'],
    ['assignedDate', 'Assigned', 'date'],
  ],
  contacts: [
    ['contactId', 'Contact ID'],
    ['name', 'Name'],
    ['title', 'Title'],
    ['email', 'Email'],
    ['roleType', 'Role'],
    ['primaryContact', 'Primary', 'boolean'],
  ],
  subscriptions: [
    ['fund', 'Fund'],
    ['currentNavUsdMm', 'Current NAV (USD mm)', 'number'],
    ['initialSubscriptionDate', 'Subscribed', 'date'],
    ['cumulativeNetReturnPct', 'Net return (%)', 'number'],
  ],
  diligence: [
    ['ddqType', 'Type'],
    ['ddqStatus', 'DDQ status', 'status'],
    ['dueDate', 'Due', 'date'],
    ['targetCompletionDate', 'Target', 'date'],
  ],
  tasks: [
    ['taskId', 'Task ID'],
    ['description', 'Description'],
    ['owner', 'Owner'],
    ['dueDate', 'Due', 'date'],
    ['priority', 'Priority', 'status'],
    ['status', 'Status', 'status'],
  ],
  activities: [
    ['activityId', 'Activity ID'],
    ['date', 'Date', 'date'],
    ['type', 'Type'],
    ['subject', 'Subject'],
    ['contactName', 'Contact'],
    ['outcome', 'Outcome'],
  ],
  calendarEvents: [
    ['date', 'Date', 'date'],
    ['time', 'Time'],
    ['purpose', 'Purpose'],
    ['owner', 'Owner'],
    ['status', 'Status', 'status'],
  ],
  messages: [
    ['date', 'Date', 'datetime'],
    ['from', 'From'],
    ['subject', 'Subject'],
    ['to', 'To'],
  ],
};

const PAGE_CONFIG = {
  lps: {
    title: 'LPs',
    description: 'Manage existing limited partner relationships and their related work.',
    resource: 'relationships',
    relationshipKind: 'existing',
    newLabel: 'New LP',
    searchLabel: 'Search LPs',
    columns: [
      ['investorId', 'LP ID'],
      ['name', 'LP name', 'link'],
      ['lpType', 'LP type'],
      ['domicile', 'Domicile'],
      ['taxStatus', 'Tax status'],
      ['relationshipStatus', 'Status', 'status'],
    ],
  },
  prospects: {
    title: 'Prospects',
    description: 'Track prospective investors from initial outreach through commitment.',
    resource: 'relationships',
    relationshipKind: 'prospect',
    newLabel: 'New prospect',
    searchLabel: 'Search prospects',
    columns: [
      ['prospectId', 'Prospect ID'],
      ['name', 'Prospect name', 'link'],
      ['fundType', 'Fund type'],
      ['country', 'Country'],
      ['priorityTier', 'Priority'],
      ['pipelineStage', 'Pipeline stage', 'status'],
      ['probabilityPct', 'Probability', 'probability'],
      ['targetCommitmentUsdMm', 'Target (USD mm)', 'number'],
    ],
  },
  meetings: {
    title: 'Meetings',
    description: 'Plan and maintain meetings across LP and prospect relationships.',
    resource: 'calendarEvents',
    newLabel: 'New meeting',
    searchLabel: 'Search meetings',
    columns: [
      ['purpose', 'Purpose', 'link'],
      ['date', 'Date', 'date'],
      ['time', 'Time'],
      ['relationshipName', 'Related LP or prospect'],
      ['owner', 'Owner'],
      ['status', 'Status', 'status'],
    ],
  },
  calendar: {
    title: 'Calendar',
    description: 'View meetings and touchpoints across the current work week.',
    resource: 'calendarEvents',
    newLabel: 'New meeting',
  },
  emails: {
    title: 'Emails',
    description: 'Create, import, and review relationship correspondence.',
    resource: 'messages',
    newLabel: 'New email',
    searchLabel: 'Search emails',
    columns: [
      ['subject', 'Subject', 'link'],
      ['from', 'From'],
      ['to', 'To'],
      ['relationshipName', 'Related LP or prospect'],
      ['date', 'Date', 'datetime'],
    ],
  },
};

const state = {
  page: 'lps',
  detail: null,
  info: null,
  records: {},
  relationshipDetails: {},
  filters: {
    lps: '',
    prospects: '',
    meetings: '',
    emails: '',
  },
  calendarWeekOffset: 0,
  selectedEmailId: null,
  mailboxDetailOnMobile: false,
  cacheGeneration: 0,
  dialog: null,
  renderSequence: 0,
};

const pageElement = document.querySelector('#page');
const workspaceElement = document.querySelector('#workspace');
const recordDialog = document.querySelector('#record-dialog');
const recordForm = document.querySelector('#record-form');
const confirmDialog = document.querySelector('#confirm-dialog');

const escapeHtml = (value) =>
  String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');

const displayValue = (value) => {
  if (value === null || value === undefined || value === '') {
    return '—';
  }
  if (Array.isArray(value)) {
    return value.map(String).filter(Boolean).join(', ') || '—';
  }
  if (typeof value === 'boolean') {
    return value ? 'Yes' : 'No';
  }
  if (typeof value === 'object') {
    return '—';
  }
  return String(value);
};

const isTruthyValue = (value) =>
  value === true ||
  ['true', 'yes', '1'].includes(
    String(value ?? '')
      .trim()
      .toLowerCase(),
  );

const parseDate = (value) => {
  if (!value) {
    return null;
  }
  const date = new Date(String(value));
  return Number.isNaN(date.getTime()) ? null : date;
};

const formatDate = (value, includeTime = false) => {
  const calendarDateMatch =
    !includeTime && typeof value === 'string' ? value.match(/^(\d{4})-(\d{2})-(\d{2})$/) : null;
  const date = calendarDateMatch
    ? new Date(
        Number(calendarDateMatch[1]),
        Number(calendarDateMatch[2]) - 1,
        Number(calendarDateMatch[3]),
      )
    : parseDate(value);
  if (!date) {
    return displayValue(value);
  }
  return new Intl.DateTimeFormat('en', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    ...(includeTime ? { hour: '2-digit', minute: '2-digit' } : {}),
  }).format(date);
};

const formatValue = (value, type = 'text') => {
  if (type === 'date') {
    return formatDate(value);
  }
  if (type === 'datetime') {
    return formatDate(value, true);
  }
  if (type === 'boolean') {
    return isTruthyValue(value) ? 'Yes' : 'No';
  }
  if (type === 'number' && typeof value === 'number') {
    return new Intl.NumberFormat('en', { maximumFractionDigits: 2 }).format(value);
  }
  if (type === 'probability' && value !== null && value !== '') {
    const numericValue = Number(value);
    if (Number.isFinite(numericValue)) {
      const percent = Math.abs(numericValue) <= 1 ? numericValue * 100 : numericValue;
      return `${new Intl.NumberFormat('en', { maximumFractionDigits: 1 }).format(percent)}%`;
    }
  }
  return displayValue(value);
};

const recordLabel = (resource, record) => {
  const data = record?.data ?? {};
  const label =
    resource === 'relationships'
      ? (data.name ?? data.lpName ?? data.institution)
      : resource === 'calendarEvents'
        ? data.purpose
        : resource === 'messages'
          ? data.subject
          : (data.name ?? data.description ?? data.subject ?? data.fund ?? data.ddqType);
  return String(label || `Untitled ${RESOURCE_META[resource]?.singular ?? 'record'}`);
};

const statusTone = (value) => {
  const normalized = String(value ?? '').toLowerCase();
  if (
    ['overdue', 'urgent', 'risk', 'dormant', 'no response', 'late'].some((word) =>
      normalized.includes(word),
    )
  ) {
    return 'risk';
  }
  if (
    ['complete', 'active', 'confirmed', 'above', 'passed', 'closed'].some((word) =>
      normalized.includes(word),
    )
  ) {
    return 'good';
  }
  if (['pending', 'proposed', 'watch', 'medium'].some((word) => normalized.includes(word))) {
    return 'warning';
  }
  return normalized ? 'info' : '';
};

const statusBadge = (value) =>
  value
    ? `<span class="status ${statusTone(value)}">${escapeHtml(displayValue(value))}</span>`
    : '—';

const parseError = async (response) => {
  const fallback = `${response.status} ${response.statusText}`.trim();
  try {
    const body = await response.json();
    return body.message ?? body.error ?? fallback;
  } catch {
    return fallback;
  }
};

const request = async (path, options = {}) => {
  const response = await fetch(path, {
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers ?? {}),
    },
    ...options,
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
};

const loadInfo = async (force = false) => {
  if (!state.info || force) {
    const generation = state.cacheGeneration;
    const info = await request('/api');
    if (generation === state.cacheGeneration) {
      state.info = info;
      document.querySelector('#snapshot-date').textContent = formatDate(info.snapshotDate);
    }
    return info;
  }
  return state.info;
};

const loadResource = async (resource, force = false) => {
  if (!state.records[resource] || force) {
    const generation = state.cacheGeneration;
    const response = await request(`/api/${encodeURIComponent(resource)}`);
    if (generation === state.cacheGeneration) {
      state.records = {
        ...state.records,
        [resource]: response.items,
      };
    }
    return response.items;
  }
  return state.records[resource];
};

const loadRelationshipDetails = async (id, force = false) => {
  if (!state.relationshipDetails[id] || force) {
    const generation = state.cacheGeneration;
    const details = await request(`/api/relationship-details/${encodeURIComponent(id)}`);
    if (generation === state.cacheGeneration) {
      state.relationshipDetails = {
        ...state.relationshipDetails,
        [id]: details,
      };
    }
    return details;
  }
  return state.relationshipDetails[id];
};

const findRecord = async (resource, id) => {
  const cached = state.records[resource]?.find((record) => record.id === id);
  return cached ?? request(`/api/${encodeURIComponent(resource)}/${encodeURIComponent(id)}`);
};

const invalidateAfterWrite = (resource) => {
  state.cacheGeneration += 1;
  state.relationshipDetails = {};
  state.info = null;
  if (resource === 'relationships') {
    state.records = {};
    return;
  }
  state.records = {
    ...state.records,
    [resource]: undefined,
  };
};

const relationshipName = (relationshipId, relationships) => {
  if (!relationshipId) {
    return 'Not linked';
  }
  const relationship = relationships.find((record) => record.id === relationshipId);
  return relationship ? recordLabel('relationships', relationship) : 'Relationship unavailable';
};

const showToast = (message, tone = 'success') => {
  const toast = document.createElement('div');
  toast.className = `toast ${tone === 'error' ? 'error' : ''}`;
  toast.textContent = message;
  document.querySelector('#toast-region').append(toast);
  window.setTimeout(() => toast.remove(), 4200);
};

const loadingState = (label = 'Loading records') => `
  <div class="loading-state" role="status">
    <div class="state-copy">
      <div class="loading-mark" aria-hidden="true"></div>
      <strong>${escapeHtml(label)}</strong>
      <span>Retrieving the latest records.</span>
    </div>
  </div>
`;

const emptyState = (title, copy) => `
  <div class="empty-state">
    <div class="state-copy">
      <strong>${escapeHtml(title)}</strong>
      <span>${escapeHtml(copy)}</span>
    </div>
  </div>
`;

const errorState = () => `
  <div class="error-state" role="alert">
    <div class="state-copy">
      <strong>Records unavailable</strong>
      <p>The request could not be completed. Try again.</p>
      <button class="button secondary" type="button" data-action="retry">Try again</button>
    </div>
  </div>
`;

const pageHeading = (title, copy, actions) => `
  <header class="page-heading">
    <div>
      <h1>${escapeHtml(title)}</h1>
      <p>${escapeHtml(copy)}</p>
    </div>
    <div class="heading-actions">${actions}</div>
  </header>
`;

const valueForColumn = (record, key, relationships) =>
  key === 'relationshipName'
    ? relationshipName(record.relationshipId, relationships)
    : record.data?.[key];

const recordSearchText = (record, columns, relationships) =>
  columns
    .map(([key, , type = 'text']) =>
      formatValue(valueForColumn(record, key, relationships), type === 'link' ? 'text' : type),
    )
    .join(' ')
    .toLowerCase();

const filterRecords = (records, query, columns, relationships) => {
  const normalized = query.trim().toLowerCase();
  if (!normalized) {
    return records;
  }
  return records.filter((record) =>
    recordSearchText(record, columns, relationships).includes(normalized),
  );
};

const sortPageRecords = (records, page) => {
  if (page === 'lps' || page === 'prospects') {
    return [...records].sort((left, right) =>
      recordLabel('relationships', left).localeCompare(recordLabel('relationships', right)),
    );
  }
  const direction = page === 'emails' ? -1 : 1;
  return [...records].sort((left, right) => {
    const leftDate = parseDate(left.data?.date)?.getTime() ?? 0;
    const rightDate = parseDate(right.data?.date)?.getTime() ?? 0;
    return (leftDate - rightDate) * direction;
  });
};

const renderCell = (record, column, relationships, detailPage) => {
  const [key, , type = 'text'] = column;
  const value = valueForColumn(record, key, relationships);
  if (type === 'link') {
    return `
      <button class="record-link" type="button" data-action="open-record"
        data-resource="${escapeHtml(PAGE_CONFIG[detailPage].resource)}"
        data-id="${escapeHtml(record.id)}">
        ${escapeHtml(displayValue(value))}
      </button>
    `;
  }
  if (type === 'status') {
    return statusBadge(value);
  }
  const content = escapeHtml(formatValue(value, type));
  return ['text', 'datetime'].includes(type)
    ? `<span class="cell-truncate" title="${content}">${content}</span>`
    : content;
};

const renderListTable = (records, columns, relationships, page) => {
  const header = columns.map(([, label]) => `<th scope="col">${escapeHtml(label)}</th>`).join('');
  const rows = records
    .map(
      (record) => `
        <tr>
          ${columns
            .map((column) => `<td>${renderCell(record, column, relationships, page)}</td>`)
            .join('')}
        </tr>
      `,
    )
    .join('');
  return `
    <div class="data-table-wrap">
      <table class="data-table">
        <caption class="sr-only">${escapeHtml(PAGE_CONFIG[page].title)} records</caption>
        <thead><tr>${header}</tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
};

const renderListPage = async () => {
  const pageConfig = PAGE_CONFIG[state.page];
  const [sourceRecords, relationships] = await Promise.all([
    loadResource(pageConfig.resource),
    loadResource('relationships'),
  ]);
  const kindFiltered = pageConfig.relationshipKind
    ? sourceRecords.filter((record) => record.data?.kind === pageConfig.relationshipKind)
    : sourceRecords;
  const sorted = sortPageRecords(kindFiltered, state.page);
  const filtered = filterRecords(
    sorted,
    state.filters[state.page],
    pageConfig.columns,
    relationships,
  );
  const importAction =
    state.page === 'emails'
      ? '<button class="button secondary" type="button" data-action="import-message">Paste email</button>'
      : '';
  const headingActions = `
    ${importAction}
    <button class="button primary" type="button" data-action="add-record"
      data-resource="${escapeHtml(pageConfig.resource)}"
      ${pageConfig.relationshipKind ? `data-relationship-kind="${pageConfig.relationshipKind}"` : ''}>
      ${escapeHtml(pageConfig.newLabel)}
    </button>
  `;
  const noRecordsCopy = `Create the first ${pageConfig.title.toLowerCase().replace(/s$/, '')} to get started.`;
  const content = filtered.length
    ? renderListTable(filtered, pageConfig.columns, relationships, state.page)
    : emptyState(
        state.filters[state.page] ? 'No matching records' : `No ${pageConfig.title.toLowerCase()}`,
        state.filters[state.page] ? 'Try a different search term.' : noRecordsCopy,
      );

  return `
    ${pageHeading(pageConfig.title, pageConfig.description, headingActions)}
    <section class="list-card" aria-label="${escapeHtml(pageConfig.title)} list">
      <div class="toolbar">
        <div class="search-wrap">
          <input class="filter-input" type="search" data-filter="${escapeHtml(state.page)}"
            value="${escapeHtml(state.filters[state.page])}"
            placeholder="${escapeHtml(pageConfig.searchLabel)}"
            aria-label="${escapeHtml(pageConfig.searchLabel)}" />
        </div>
        <span class="list-count">${filtered.length} of ${sorted.length}</span>
      </div>
      ${content}
    </section>
  `;
};

const calendarDay = (value) => {
  const match = typeof value === 'string' ? value.match(/^(\d{4})-(\d{2})-(\d{2})$/) : null;
  if (!match) {
    return null;
  }
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  return date.toISOString().slice(0, 10) === value ? date : null;
};

const addCalendarDays = (date, days) =>
  new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate() + days));

const calendarDateKey = (date) => date.toISOString().slice(0, 10);

const startOfCalendarWeek = (snapshotDate, weekOffset) => {
  const snapshot = calendarDay(snapshotDate);
  if (!snapshot) {
    return null;
  }
  const isoDay = snapshot.getUTCDay() || 7;
  return addCalendarDays(snapshot, 1 - isoDay + weekOffset * 7);
};

const formatCalendarDay = (date, options) =>
  new Intl.DateTimeFormat('en', { timeZone: 'UTC', ...options }).format(date);

const renderCalendarEventCard = (record, relationships) => `
  <button class="calendar-event" type="button" data-action="open-calendar-event"
    data-resource="calendarEvents" data-id="${escapeHtml(record.id)}">
    <span class="calendar-event-time">${escapeHtml(displayValue(record.data?.time))}</span>
    <span class="calendar-event-type">${escapeHtml(displayValue(record.data?.type))}</span>
    <strong>${escapeHtml(relationshipName(record.relationshipId, relationships))}</strong>
    <span class="calendar-event-purpose">${escapeHtml(displayValue(record.data?.purpose))}</span>
    <span class="calendar-event-meta">${escapeHtml(displayValue(record.data?.owner))}</span>
    ${statusBadge(record.data?.status)}
  </button>
`;

const calendarTimeSortValue = (value) => {
  const time = String(value ?? '');
  const twelveHourMatch = time.match(/\b(0?[1-9]|1[0-2]):([0-5]\d)\s*(AM|PM)\b/i);
  if (twelveHourMatch) {
    const hour =
      (Number(twelveHourMatch[1]) % 12) + (twelveHourMatch[3].toUpperCase() === 'PM' ? 12 : 0);
    return hour * 60 + Number(twelveHourMatch[2]);
  }
  const twentyFourHourMatch = time.match(/^([01]\d|2[0-3]):([0-5]\d)\b/);
  return twentyFourHourMatch
    ? Number(twentyFourHourMatch[1]) * 60 + Number(twentyFourHourMatch[2])
    : Number.POSITIVE_INFINITY;
};

const renderCalendarPage = async () => {
  const [events, relationships, info] = await Promise.all([
    loadResource('calendarEvents'),
    loadResource('relationships'),
    loadInfo(),
  ]);
  const weekStart = startOfCalendarWeek(info.snapshotDate, state.calendarWeekOffset);
  if (!weekStart) {
    return errorState();
  }
  const days = Array.from({ length: 7 }, (_, index) => addCalendarDays(weekStart, index));
  const eventsByDay = new Map(days.map((date) => [calendarDateKey(date), []]));
  const unscheduled = [];
  for (const event of events) {
    const date = calendarDay(event.data?.date);
    const dayEvents = date ? eventsByDay.get(calendarDateKey(date)) : null;
    if (dayEvents) {
      dayEvents.push(event);
    } else if (!date) {
      unscheduled.push(event);
    }
  }
  for (const dayEvents of eventsByDay.values()) {
    dayEvents.sort((left, right) => {
      const timeDifference =
        calendarTimeSortValue(left.data?.time) - calendarTimeSortValue(right.data?.time);
      return (
        timeDifference ||
        String(left.data?.time ?? '').localeCompare(String(right.data?.time ?? ''))
      );
    });
  }
  const weekEnd = days.at(-1);
  const dateRange = `${formatCalendarDay(weekStart, {
    day: 'numeric',
    month: 'short',
  })} – ${formatCalendarDay(weekEnd, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })}`;
  const headingActions = `
    <button class="button primary" type="button" data-action="add-record"
      data-resource="calendarEvents">New meeting</button>
  `;
  const week = days
    .map((date) => {
      const key = calendarDateKey(date);
      const dayEvents = eventsByDay.get(key);
      return `
        <section class="calendar-day" aria-labelledby="calendar-day-${key}">
          <header>
            <span>${escapeHtml(formatCalendarDay(date, { weekday: 'short' }))}</span>
            <h2 id="calendar-day-${key}">${escapeHtml(
              formatCalendarDay(date, {
                day: 'numeric',
                month: 'short',
              }),
            )}</h2>
          </header>
          <div class="calendar-day-events">
            ${
              dayEvents.length
                ? dayEvents.map((event) => renderCalendarEventCard(event, relationships)).join('')
                : '<p class="calendar-empty">No meetings</p>'
            }
          </div>
        </section>
      `;
    })
    .join('');
  return `
    ${pageHeading(PAGE_CONFIG.calendar.title, PAGE_CONFIG.calendar.description, headingActions)}
    <section class="calendar-shell" aria-label="Weekly calendar">
      <div class="calendar-toolbar">
        <div class="calendar-controls" aria-label="Choose week">
          <button class="button secondary" type="button" data-action="change-week"
            data-week-delta="-1">Previous week</button>
          <button class="button secondary" type="button" data-action="this-week">This week</button>
          <button class="button secondary" type="button" data-action="change-week"
            data-week-delta="1">Next week</button>
        </div>
        <h2>${escapeHtml(dateRange)}</h2>
      </div>
      <div class="work-week">${week}</div>
    </section>
    ${
      unscheduled.length
        ? `
          <section class="unscheduled-section">
            <header>
              <div>
                <h2>Unscheduled</h2>
                <p>Meetings with an invalid or TBD date.</p>
              </div>
              <span>${unscheduled.length}</span>
            </header>
            <div class="unscheduled-grid">
              ${unscheduled.map((event) => renderCalendarEventCard(event, relationships)).join('')}
            </div>
          </section>
        `
        : ''
    }
  `;
};

const messagePreview = (value) =>
  String(value ?? '')
    .replace(/\s+/g, ' ')
    .trim();

const renderMailboxDetail = (record, relationships) => {
  if (!record) {
    return `
      <div class="mailbox-empty-detail">
        <div>
          <strong>No message selected</strong>
          <span>Choose a message to read it here.</span>
        </div>
      </div>
    `;
  }
  const linkedName = relationshipName(record.relationshipId, relationships);
  return `
    <article class="mail-reader" aria-labelledby="selected-email-subject">
      <button class="back-button mailbox-back" type="button" data-action="back-to-messages">
        Back to messages
      </button>
      <header class="mail-reader-header">
        <div>
          <p class="eyebrow">Email</p>
          <h2 id="selected-email-subject">${escapeHtml(displayValue(record.data?.subject))}</h2>
        </div>
        <div class="record-actions">
          <button class="button secondary" type="button" data-action="edit-record"
            data-resource="messages" data-id="${escapeHtml(record.id)}">Edit</button>
          <button class="button danger" type="button" data-action="delete-record"
            data-resource="messages" data-id="${escapeHtml(record.id)}">Delete</button>
        </div>
      </header>
      <dl class="mail-metadata">
        <div><dt>From</dt><dd>${escapeHtml(displayValue(record.data?.from))}</dd></div>
        <div><dt>To</dt><dd>${escapeHtml(displayValue(record.data?.to))}</dd></div>
        <div><dt>Cc</dt><dd>${escapeHtml(displayValue(record.data?.cc))}</dd></div>
        <div><dt>Date</dt><dd>${escapeHtml(formatDate(record.data?.date, true))}</dd></div>
        <div><dt>Relationship</dt><dd>${escapeHtml(linkedName)}</dd></div>
      </dl>
      <div class="mail-paper">${escapeHtml(displayValue(record.data?.body))}</div>
    </article>
  `;
};

const renderEmailsPage = async () => {
  const [messages, relationships] = await Promise.all([
    loadResource('messages'),
    loadResource('relationships'),
  ]);
  const sorted = sortPageRecords(messages, 'emails');
  const normalizedFilter = state.filters.emails.trim().toLowerCase();
  const filtered = normalizedFilter
    ? sorted.filter((record) =>
        [
          record.data?.from,
          record.data?.to,
          record.data?.cc,
          record.data?.subject,
          record.data?.body,
          relationshipName(record.relationshipId, relationships),
          formatDate(record.data?.date, true),
        ]
          .map(displayValue)
          .join(' ')
          .toLowerCase()
          .includes(normalizedFilter),
      )
    : sorted;
  const isMobile = window.matchMedia('(max-width: 820px)').matches;
  if (!filtered.some((record) => record.id === state.selectedEmailId)) {
    state.selectedEmailId = isMobile ? null : (filtered[0]?.id ?? null);
    if (isMobile) {
      state.mailboxDetailOnMobile = false;
    }
  }
  const selected = filtered.find((record) => record.id === state.selectedEmailId) ?? null;
  const headingActions = `
    <button class="button secondary" type="button" data-action="import-message">Paste email</button>
    <button class="button primary" type="button" data-action="add-record"
      data-resource="messages">New email</button>
  `;
  const rows = filtered
    .map((record) => {
      const isSelected = record.id === state.selectedEmailId;
      return `
        <button class="mail-row ${isSelected ? 'is-selected' : ''}" type="button"
          data-action="select-email" data-id="${escapeHtml(record.id)}"
          ${isSelected ? 'aria-current="true"' : ''}>
          <span class="mail-row-top">
            <strong>${escapeHtml(displayValue(record.data?.from))}</strong>
            <time datetime="${escapeHtml(record.data?.date ?? '')}">${escapeHtml(
              formatDate(record.data?.date),
            )}</time>
          </span>
          <span class="mail-row-subject">${escapeHtml(displayValue(record.data?.subject))}</span>
          <span class="mail-row-preview">${escapeHtml(messagePreview(record.data?.body))}</span>
          <span class="mail-row-relationship">${escapeHtml(
            relationshipName(record.relationshipId, relationships),
          )}</span>
        </button>
      `;
    })
    .join('');
  return `
    ${pageHeading(PAGE_CONFIG.emails.title, PAGE_CONFIG.emails.description, headingActions)}
    <section class="mailbox ${state.mailboxDetailOnMobile ? 'show-detail' : ''}"
      aria-label="Email mailbox">
      <div class="mail-list-pane">
        <div class="mailbox-toolbar">
          <div class="search-wrap">
            <input class="filter-input" type="search" data-filter="emails"
              value="${escapeHtml(state.filters.emails)}"
              placeholder="Search emails" aria-label="Search emails" />
          </div>
          <span class="list-count">${filtered.length} of ${sorted.length}</span>
        </div>
        <div class="mail-rows" aria-label="Messages">
          ${
            rows ||
            emptyState(
              state.filters.emails ? 'No matching messages' : 'No emails',
              state.filters.emails
                ? 'Try a different search term.'
                : 'Create or paste the first email.',
            )
          }
        </div>
      </div>
      <div class="mail-detail-pane">${renderMailboxDetail(selected, relationships)}</div>
    </section>
  `;
};

const fieldsForResource = (resource, relationshipKind) => {
  if (resource === 'relationships') {
    return RELATIONSHIP_FIELDS[relationshipKind === 'prospect' ? 'prospect' : 'existing'];
  }
  const fields = FIELD_CONFIG[resource] ?? [];
  if (resource !== 'diligence') {
    return fields;
  }
  return fields.filter(([key]) =>
    relationshipKind === 'prospect' ? key !== 'status' : key !== 'ddqStatus',
  );
};

const renderDetailFields = (record, fields, options = {}) => {
  const additionalFields = options.relationshipName
    ? [['relationshipName', 'Related LP or prospect']]
    : [];
  return [...additionalFields, ...fields]
    .map(([key, label, type = 'text']) => {
      const value = key === 'relationshipName' ? options.relationshipName : record.data?.[key];
      return `
        <div class="detail-field">
          <dt>${escapeHtml(label)}</dt>
          <dd>${escapeHtml(formatValue(value, type === 'datetime-local' ? 'datetime' : type))}</dd>
        </div>
      `;
    })
    .join('');
};

const renderRelatedTable = (resource, records, relationshipId, relationshipKind) => {
  if (!records.length) {
    return emptyState(
      `No ${RESOURCE_META[resource].label.toLowerCase()}`,
      `Add the first ${RESOURCE_META[resource].singular} for this relationship.`,
    );
  }
  const columns =
    resource === 'diligence'
      ? RELATED_COLUMNS[resource].map((column) =>
          column[0] === 'ddqStatus'
            ? [relationshipKind === 'prospect' ? 'ddqStatus' : 'status', 'Status', 'status']
            : column,
        )
      : RELATED_COLUMNS[resource];
  const header = [
    ...columns.map(([, label]) => `<th scope="col">${escapeHtml(label)}</th>`),
    '<th scope="col"><span class="sr-only">Actions</span></th>',
  ].join('');
  const rows = records
    .map(
      (record) => `
        <tr>
          ${columns
            .map(([key, , type = 'text']) => {
              const value = record.data?.[key];
              const rendered =
                type === 'status' ? statusBadge(value) : escapeHtml(formatValue(value, type));
              return `<td><span class="cell-truncate">${rendered}</span></td>`;
            })
            .join('')}
          <td class="row-action">
            <button class="button ghost" type="button" data-action="edit-record"
              data-resource="${escapeHtml(resource)}" data-id="${escapeHtml(record.id)}"
              data-relationship-id="${escapeHtml(relationshipId)}">Edit</button>
            <button class="button ghost danger-text" type="button" data-action="delete-record"
              data-resource="${escapeHtml(resource)}" data-id="${escapeHtml(record.id)}">Delete</button>
          </td>
        </tr>
      `,
    )
    .join('');
  return `
    <div class="data-table-wrap">
      <table class="data-table">
        <caption class="sr-only">${escapeHtml(RESOURCE_META[resource].label)}</caption>
        <thead><tr>${header}</tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
};

const renderRelationshipDetail = async (id) => {
  const details = await loadRelationshipDetails(id);
  const relationship = details.relationship;
  const kind = relationship.data?.kind === 'prospect' ? 'prospect' : 'existing';
  const page = kind === 'prospect' ? 'prospects' : 'lps';
  const relatedSections = RELATED_RESOURCES.map((resource) => {
    const records = details.related[resource] ?? [];
    return `
      <section class="related-section">
        <header class="related-header">
          <div>
            <h2>${escapeHtml(RESOURCE_META[resource].label)}</h2>
            <span>${records.length} ${records.length === 1 ? 'record' : 'records'}</span>
          </div>
          <button class="button small secondary" type="button" data-action="add-record"
            data-resource="${escapeHtml(resource)}" data-relationship-id="${escapeHtml(id)}">
            New
          </button>
        </header>
        ${renderRelatedTable(resource, records, id, kind)}
      </section>
    `;
  }).join('');
  return `
    <button class="back-button" type="button" data-action="back-to-list">
      Back to ${escapeHtml(PAGE_CONFIG[page].title)}
    </button>
    <article>
      <header class="record-header">
        <div>
          <p class="eyebrow">${kind === 'prospect' ? 'Prospect' : 'LP'} record</p>
          <h1>${escapeHtml(recordLabel('relationships', relationship))}</h1>
        </div>
        <div class="record-actions">
          <button class="button secondary" type="button" data-action="edit-record"
            data-resource="relationships" data-id="${escapeHtml(id)}">Edit</button>
          <button class="button danger" type="button" data-action="delete-record"
            data-resource="relationships" data-id="${escapeHtml(id)}">Delete</button>
        </div>
      </header>
      <div class="record-body">
        <section class="detail-card">
          <header class="record-section-title"><h2>Details</h2></header>
          <dl class="record-grid">
            ${renderDetailFields(relationship, fieldsForResource('relationships', kind))}
          </dl>
        </section>
        <div class="related-groups">${relatedSections}</div>
      </div>
    </article>
  `;
};

const renderSimpleDetail = async (resource, id) => {
  const [record, relationships] = await Promise.all([
    findRecord(resource, id),
    loadResource('relationships'),
  ]);
  const page = state.detail?.returnPage ?? (resource === 'calendarEvents' ? 'meetings' : 'emails');
  const fields = fieldsForResource(resource);
  const bodyField = resource === 'messages' ? fields.find(([key]) => key === 'body') : null;
  const summaryFields = bodyField ? fields.filter(([key]) => key !== 'body') : fields;
  const linkedName = relationshipName(record.relationshipId, relationships);
  return `
    <button class="back-button" type="button" data-action="back-to-list">
      Back to ${escapeHtml(PAGE_CONFIG[page].title)}
    </button>
    <article>
      <header class="record-header">
        <div>
          <p class="eyebrow">${escapeHtml(RESOURCE_META[resource].singular)}</p>
          <h1>${escapeHtml(recordLabel(resource, record))}</h1>
        </div>
        <div class="record-actions">
          <button class="button secondary" type="button" data-action="edit-record"
            data-resource="${escapeHtml(resource)}" data-id="${escapeHtml(id)}">Edit</button>
          <button class="button danger" type="button" data-action="delete-record"
            data-resource="${escapeHtml(resource)}" data-id="${escapeHtml(id)}">Delete</button>
        </div>
      </header>
      <div class="record-body">
        <section class="detail-card">
          <header class="record-section-title"><h2>Details</h2></header>
          <dl class="record-grid">
            ${renderDetailFields(record, summaryFields, { relationshipName: linkedName })}
          </dl>
          ${
            bodyField
              ? `<div class="mail-body">${escapeHtml(displayValue(record.data?.body))}</div>`
              : ''
          }
        </section>
      </div>
    </article>
  `;
};

const renderPage = async (showLoading = true) => {
  const sequence = state.renderSequence + 1;
  state.renderSequence = sequence;
  if (showLoading) {
    const label = state.detail ? 'Loading record' : `Loading ${PAGE_CONFIG[state.page].title}`;
    pageElement.innerHTML = loadingState(label);
  }
  try {
    const html = state.detail
      ? state.detail.resource === 'relationships'
        ? await renderRelationshipDetail(state.detail.id)
        : await renderSimpleDetail(state.detail.resource, state.detail.id)
      : state.page === 'calendar'
        ? await renderCalendarPage()
        : state.page === 'emails'
          ? await renderEmailsPage()
          : await renderListPage();
    if (sequence === state.renderSequence) {
      pageElement.innerHTML = html;
    }
  } catch (error) {
    if (sequence === state.renderSequence) {
      pageElement.innerHTML = errorState(error);
    }
  }
};

const moveToTop = () => {
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  window.scrollTo({ top: 0, behavior: reducedMotion ? 'auto' : 'smooth' });
};

const setPage = async (page) => {
  state.page = page;
  state.detail = null;
  if (page === 'emails') {
    state.mailboxDetailOnMobile = false;
  }
  document.querySelectorAll('.top-tab').forEach((tab) => {
    const isActive = tab.dataset.page === page;
    tab.classList.toggle('is-active', isActive);
    if (isActive) {
      tab.setAttribute('aria-current', 'page');
    } else {
      tab.removeAttribute('aria-current');
    }
  });
  await renderPage();
  workspaceElement.focus({ preventScroll: true });
  moveToTop();
};

const openDetail = async (resource, id, returnPage = state.page) => {
  state.detail = { resource, id, returnPage };
  await renderPage();
  workspaceElement.focus({ preventScroll: true });
  moveToTop();
};

const relationshipOptions = async (selectedId) => {
  const relationships = [...(await loadResource('relationships'))].sort((left, right) =>
    recordLabel('relationships', left).localeCompare(recordLabel('relationships', right)),
  );
  return [
    '<option value="">Not linked</option>',
    ...relationships.map(
      (record) => `
        <option value="${escapeHtml(record.id)}" ${record.id === selectedId ? 'selected' : ''}>
          ${escapeHtml(recordLabel('relationships', record))}
        </option>
      `,
    ),
  ].join('');
};

const browserLocalDateTimeValue = (sourceValue) => {
  const date = parseDate(sourceValue);
  if (!date) {
    return sourceValue;
  }
  const pad = (value) => String(value).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`;
};

const formInputValue = (sourceValue, type) => {
  if (Array.isArray(sourceValue)) {
    return sourceValue.join('\n');
  }
  if (type === 'probability' && sourceValue !== null && sourceValue !== '') {
    const numericValue = Number(sourceValue);
    if (Number.isFinite(numericValue)) {
      return Math.abs(numericValue) <= 1 ? numericValue * 100 : numericValue;
    }
  }
  if (type === 'datetime-local' && sourceValue) {
    return browserLocalDateTimeValue(sourceValue);
  }
  return sourceValue ?? '';
};

const isPlainEmailAddress = (value) => /^[^\s<>@]+@[^\s<>@]+$/.test(String(value));

const actualInputType = (configuredType, value) => {
  if (configuredType === 'probability') {
    return value === '' || Number.isFinite(Number(value)) ? 'number' : 'text';
  }
  if (configuredType === 'number' && value !== '' && !Number.isFinite(Number(value))) {
    return 'text';
  }
  if (configuredType === 'email' && value && !isPlainEmailAddress(value)) {
    return 'text';
  }
  if (configuredType === 'date' && value && !/^\d{4}-\d{2}-\d{2}$/.test(String(value))) {
    return 'text';
  }
  if (configuredType === 'time' && value && !/^\d{2}:\d{2}$/.test(String(value))) {
    return 'text';
  }
  if (
    configuredType === 'datetime-local' &&
    value &&
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(String(value))
  ) {
    return 'text';
  }
  return configuredType;
};

const optionsForField = (resource, relationshipKind, key) => {
  const kindSpecific = `${resource}.${relationshipKind}.${key}`;
  return OPTION_CATALOG[kindSpecific] ?? OPTION_CATALOG[`${resource}.${key}`] ?? [];
};

const renderInput = (field, record, resource, relationshipKind) => {
  const [key, label, configuredType = 'text', options = {}] = field;
  const sourceValue = record?.data?.[key];
  const value = formInputValue(sourceValue, configuredType);
  const type = actualInputType(configuredType, value);
  const fieldClass = options.full || ['textarea', 'list'].includes(configuredType) ? ' full' : '';
  const required = options.required ? ' required' : '';
  if (configuredType === 'readonly-id') {
    return `
      <div class="form-field">
        <label for="field-${escapeHtml(key)}">${escapeHtml(label)}</label>
        <input id="field-${escapeHtml(key)}" name="${escapeHtml(key)}" type="text"
          value="${escapeHtml(value)}" placeholder="Assigned on save" readonly />
        <p class="hint">${record ? 'Business ID cannot be changed.' : 'Assigned automatically on save.'}</p>
      </div>
    `;
  }
  if (configuredType === 'select') {
    const catalog = optionsForField(resource, relationshipKind, key);
    const values =
      value && !catalog.includes(String(value)) ? [String(value), ...catalog] : catalog;
    const optionMarkup = [
      '<option value="">Select an option</option>',
      ...values.map(
        (option) =>
          `<option value="${escapeHtml(option)}" ${String(value) === option ? 'selected' : ''}>${escapeHtml(option)}</option>`,
      ),
    ].join('');
    return `
      <div class="form-field${fieldClass}">
        <label for="field-${escapeHtml(key)}">${escapeHtml(label)}</label>
        <select id="field-${escapeHtml(key)}" name="${escapeHtml(key)}"
          data-value-type="select"${required}>${optionMarkup}</select>
      </div>
    `;
  }
  if (configuredType === 'checkbox') {
    return `
      <div class="form-field${fieldClass}">
        <span>${escapeHtml(label)}</span>
        <label class="checkbox-field" for="field-${escapeHtml(key)}">
          <input id="field-${escapeHtml(key)}" name="${escapeHtml(key)}" type="checkbox"
            data-value-type="checkbox" ${isTruthyValue(sourceValue) ? 'checked' : ''} />
          Yes
        </label>
      </div>
    `;
  }
  if (configuredType === 'textarea' || configuredType === 'list') {
    return `
      <div class="form-field${fieldClass}">
        <label for="field-${escapeHtml(key)}">${escapeHtml(label)}</label>
        <textarea class="${options.tall ? 'tall' : ''}" id="field-${escapeHtml(key)}"
          name="${escapeHtml(key)}" data-value-type="${escapeHtml(configuredType)}"
          ${required}>${escapeHtml(value)}</textarea>
        ${
          configuredType === 'list'
            ? '<p class="hint">Enter one item per line or separate items with commas.</p>'
            : ''
        }
      </div>
    `;
  }
  const browserType = ['text', 'email', 'tel', 'number', 'date', 'time', 'datetime-local'].includes(
    type,
  )
    ? type
    : 'text';
  const valueType =
    configuredType === 'probability' && browserType === 'number' ? 'probability' : type;
  const step = browserType === 'number' ? ` step="${escapeHtml(options.step ?? 'any')}"` : '';
  const min = browserType === 'number' && options.min ? ` min="${escapeHtml(options.min)}"` : '';
  const max = browserType === 'number' && options.max ? ` max="${escapeHtml(options.max)}"` : '';
  const roundTripValues = ['datetime-local', 'probability'].includes(valueType)
    ? ` data-original-value="${escapeHtml(sourceValue ?? '')}" data-normalized-value="${escapeHtml(value)}"`
    : '';
  return `
    <div class="form-field${fieldClass}">
      <label for="field-${escapeHtml(key)}">${escapeHtml(label)}</label>
      <input id="field-${escapeHtml(key)}" name="${escapeHtml(key)}"
        type="${escapeHtml(browserType)}" value="${escapeHtml(value)}"
        data-value-type="${escapeHtml(valueType)}"${roundTripValues}${step}${min}${max}${required} />
    </div>
  `;
};

const dialogLabels = (resource, relationshipKind) => {
  if (resource === 'relationships') {
    return relationshipKind === 'prospect'
      ? { category: 'Prospects', singular: 'prospect' }
      : { category: 'LPs', singular: 'LP' };
  }
  return {
    category: RESOURCE_META[resource].label,
    singular: RESOURCE_META[resource].singular,
  };
};

const openRecordDialog = async (
  resource,
  record = null,
  fixedRelationshipId = null,
  requestedRelationshipKind = null,
) => {
  const isEdit = Boolean(record);
  const selectedRelationship = record?.relationshipId ?? fixedRelationshipId ?? '';
  if (
    resource === 'diligence' &&
    selectedRelationship &&
    !relationshipForId(selectedRelationship)
  ) {
    await loadResource('relationships');
  }
  const relationshipKind =
    resource === 'relationships'
      ? record?.data?.kind === 'prospect' || requestedRelationshipKind === 'prospect'
        ? 'prospect'
        : 'existing'
      : resource === 'diligence' && relationshipKindForId(selectedRelationship) === 'prospect'
        ? 'prospect'
        : 'existing';
  state.dialog = {
    type: 'record',
    resource,
    record,
    relationshipId: fixedRelationshipId,
    relationshipKind,
  };
  const labels = dialogLabels(resource, relationshipKind);
  document.querySelector('#dialog-eyebrow').textContent = labels.category;
  document.querySelector('#dialog-title').textContent =
    `${isEdit ? 'Edit' : 'New'} ${labels.singular}`;
  document.querySelector('#dialog-submit').textContent = isEdit
    ? 'Save changes'
    : `Create ${labels.singular}`;

  const showRelationshipSelector = resource !== 'relationships' && !fixedRelationshipId;
  const relationshipField = showRelationshipSelector
    ? `
      <div class="form-field full">
        <label for="record-relationship">Related LP or prospect</label>
        <select id="record-relationship" name="relationshipId">
          ${await relationshipOptions(selectedRelationship)}
        </select>
      </div>
    `
    : '';
  const fields = fieldsForResource(resource, relationshipKind)
    .map((field) => renderInput(field, record, resource, relationshipKind))
    .join('');
  document.querySelector('#record-fields').innerHTML = `
    <div class="form-grid">
      ${relationshipField}
      ${fields}
      <div id="form-error" class="form-error full" role="alert" hidden></div>
    </div>
  `;
  recordDialog.showModal();
  window.setTimeout(() => recordDialog.querySelector('input, select, textarea')?.focus(), 0);
};

const openImportDialog = async () => {
  state.dialog = { type: 'import' };
  document.querySelector('#dialog-eyebrow').textContent = 'Emails';
  document.querySelector('#dialog-title').textContent = 'Paste email';
  document.querySelector('#dialog-submit').textContent = 'Import email';
  document.querySelector('#record-fields').innerHTML = `
    <div class="form-grid">
      <div class="form-field full">
        <label for="record-relationship">Related LP or prospect</label>
        <select id="record-relationship" name="relationshipId">
          ${await relationshipOptions('')}
        </select>
      </div>
      <div class="form-field full">
        <label for="raw-email">Email content</label>
        <textarea class="tall" id="raw-email" name="rawEmail" required
          placeholder="Paste the complete email, including headers and body."></textarea>
        <p class="hint">Include From, To, Subject, Date, a blank line, and the message body.</p>
      </div>
      <div id="form-error" class="form-error full" role="alert" hidden></div>
    </div>
  `;
  recordDialog.showModal();
  window.setTimeout(() => document.querySelector('#raw-email')?.focus(), 0);
};

const readFieldValue = (form, key) => {
  const control = form.elements.namedItem(key);
  if (
    !(
      control instanceof HTMLInputElement ||
      control instanceof HTMLTextAreaElement ||
      control instanceof HTMLSelectElement
    )
  ) {
    return '';
  }
  const type = control.dataset.valueType ?? 'text';
  if (type === 'checkbox') {
    return control.checked;
  }
  const rawValue = control.value.trim();
  if (
    type === 'datetime-local' &&
    rawValue === control.dataset.normalizedValue &&
    control.dataset.originalValue !== undefined
  ) {
    return control.dataset.originalValue;
  }
  if (type === 'datetime-local') {
    const date = new Date(rawValue);
    return Number.isNaN(date.getTime()) ? rawValue : date.toISOString();
  }
  if (type === 'probability') {
    if (
      rawValue === control.dataset.normalizedValue &&
      control.dataset.originalValue !== undefined
    ) {
      return control.dataset.originalValue === '' ? null : Number(control.dataset.originalValue);
    }
    return rawValue === '' ? null : Number(rawValue) / 100;
  }
  if (type === 'list') {
    return rawValue
      .split(/[\n,]/)
      .map((item) => item.trim())
      .filter(Boolean);
  }
  if (type === 'number') {
    return rawValue === '' ? null : Number(rawValue);
  }
  return rawValue;
};

const relationshipForId = (relationshipId) =>
  state.records.relationships?.find((record) => record.id === relationshipId) ??
  state.relationshipDetails[relationshipId]?.relationship;

const relationshipKindForId = (relationshipId) => relationshipForId(relationshipId)?.data?.kind;

const RELATIONSHIP_ALIAS_KEYS = ['investorId', 'prospectId', 'lpName', 'institution'];

const withoutRelationshipAliases = (sourceData) =>
  Object.fromEntries(
    Object.entries(sourceData).filter(([key]) => !RELATIONSHIP_ALIAS_KEYS.includes(key)),
  );

const clearedRelationshipAliases = (sourceData) =>
  Object.fromEntries(
    RELATIONSHIP_ALIAS_KEYS.filter((key) => Object.hasOwn(sourceData, key)).map((key) => [
      key,
      null,
    ]),
  );

const formDataToRecordInput = (form, dialogState) => {
  const { resource, record, relationshipKind, relationshipId: fixedRelationshipId } = dialogState;
  const fields = fieldsForResource(resource, relationshipKind);
  const editableData = Object.fromEntries(
    fields
      .filter(([, , type = 'text']) => type !== 'readonly-id')
      .map(([key]) => [key, readFieldValue(form, key)]),
  );
  const formData = new FormData(form);
  const relationshipId =
    resource === 'relationships'
      ? record?.relationshipId
      : (fixedRelationshipId ?? (String(formData.get('relationshipId') ?? '').trim() || null));
  const preservedData =
    resource === 'relationships'
      ? { ...(record?.data ?? {}) }
      : withoutRelationshipAliases(record?.data ?? {});
  const data = {
    ...preservedData,
    ...(resource === 'relationships' ? {} : clearedRelationshipAliases(record?.data ?? {})),
    ...editableData,
  };
  if (resource === 'relationships') {
    data.kind = relationshipKind;
    data.name = editableData.name;
    if (relationshipKind === 'prospect') {
      data.institution = editableData.name;
    } else {
      data.lpName = editableData.name;
    }
  }
  if (resource !== 'relationships' && resource !== 'messages' && relationshipId) {
    const relationship = relationshipForId(relationshipId);
    if (relationship?.data?.kind === 'prospect') {
      data.prospectId = relationship.data.prospectId ?? relationship.id;
      data.institution =
        relationship.data.institution ??
        relationship.data.name ??
        recordLabel('relationships', relationship);
    } else if (relationship) {
      data.investorId = relationship.data.investorId ?? relationship.id;
      data.lpName =
        relationship.data.lpName ??
        relationship.data.name ??
        recordLabel('relationships', relationship);
    }
  }
  if (resource === 'calendarEvents') {
    const linkedKind = relationshipKindForId(relationshipId);
    data.kind = linkedKind
      ? linkedKind === 'prospect'
        ? 'touchpoint'
        : 'meeting'
      : (record?.data?.kind ?? 'meeting');
  }
  return {
    ...(resource !== 'relationships' || relationshipId !== undefined
      ? { relationshipId: relationshipId ?? null }
      : {}),
    data,
  };
};

const showFormError = () => {
  const errorElement = document.querySelector('#form-error');
  errorElement.textContent = 'The record could not be saved. Check the fields and try again.';
  errorElement.hidden = false;
};

const submitRecordForm = async () => {
  const dialogState = state.dialog;
  if (!dialogState) {
    return;
  }
  const submitButton = document.querySelector('#dialog-submit');
  submitButton.disabled = true;
  document.querySelector('#form-error').hidden = true;
  try {
    if (dialogState.type === 'import') {
      const formData = new FormData(recordForm);
      const created = await request('/api/messages/import', {
        method: 'POST',
        body: JSON.stringify({
          rawEmail: String(formData.get('rawEmail') ?? ''),
          relationshipId: String(formData.get('relationshipId') ?? '').trim() || null,
        }),
      });
      invalidateAfterWrite('messages');
      state.selectedEmailId = created.id;
      state.mailboxDetailOnMobile = true;
      state.filters = { ...state.filters, emails: '' };
      recordDialog.close();
      showToast('Email imported');
      await renderPage(false);
      return;
    }

    const { resource, record } = dialogState;
    const input = formDataToRecordInput(recordForm, dialogState);
    const isEdit = Boolean(record);
    const path = isEdit
      ? `/api/${encodeURIComponent(resource)}/${encodeURIComponent(record.id)}`
      : `/api/${encodeURIComponent(resource)}`;
    const saved = await request(path, {
      method: isEdit ? 'PATCH' : 'POST',
      body: JSON.stringify(input),
    });
    invalidateAfterWrite(resource);
    if (resource === 'messages') {
      state.selectedEmailId = saved.id;
      state.mailboxDetailOnMobile = true;
      state.filters = { ...state.filters, emails: '' };
    }
    recordDialog.close();
    showToast(isEdit ? 'Changes saved' : 'Record created');
    await renderPage(false);
    void loadInfo(true).catch(() => {});
  } catch {
    showFormError();
  } finally {
    submitButton.disabled = false;
  }
};

const confirmAction = (title, copy, actionLabel) =>
  new Promise((resolve) => {
    document.querySelector('#confirm-title').textContent = title;
    document.querySelector('#confirm-copy').textContent = copy;
    document.querySelector('#confirm-action').textContent = actionLabel;
    const handleClose = () => {
      confirmDialog.removeEventListener('close', handleClose);
      resolve(confirmDialog.returnValue === 'confirm');
    };
    confirmDialog.addEventListener('close', handleClose);
    confirmDialog.showModal();
    window.setTimeout(() => document.querySelector('#confirm-action').focus(), 0);
  });

const deleteRecord = async (resource, id) => {
  let record;
  try {
    record = await findRecord(resource, id);
  } catch {
    showToast('Record could not be opened', 'error');
    return;
  }
  const label = recordLabel(resource, record);
  const copy =
    resource === 'relationships'
      ? `This removes “${label}” and all of its related records from the current demo session.`
      : `This removes “${label}” from the current demo session.`;
  const confirmed = await confirmAction(`Delete ${label}?`, copy, 'Delete');
  if (!confirmed) {
    return;
  }
  const messageOrder =
    resource === 'messages' ? sortPageRecords(state.records.messages ?? [], 'emails') : [];
  const messageIndex = messageOrder.findIndex((message) => message.id === id);
  const nextMessageId =
    messageOrder[messageIndex + 1]?.id ?? messageOrder[messageIndex - 1]?.id ?? null;
  try {
    await request(`/api/${encodeURIComponent(resource)}/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    });
    invalidateAfterWrite(resource);
    if (state.detail?.resource === resource && state.detail.id === id) {
      state.detail = null;
    }
    if (resource === 'messages' && state.selectedEmailId === id) {
      state.selectedEmailId = nextMessageId;
      state.mailboxDetailOnMobile = Boolean(nextMessageId);
    }
    showToast('Record deleted');
    await renderPage(false);
    void loadInfo(true).catch(() => {});
  } catch {
    showToast('Record could not be deleted', 'error');
  }
};

const resetData = async () => {
  const confirmed = await confirmAction(
    'Reset all demo data?',
    'Every add, edit, and delete in this session will be discarded and the rolling current-week scenario restored.',
    'Reset demo',
  );
  if (!confirmed) {
    return;
  }
  try {
    await request('/api/reset', {
      method: 'POST',
      body: JSON.stringify({}),
    });
    state.info = null;
    state.records = {};
    state.relationshipDetails = {};
    state.cacheGeneration += 1;
    state.detail = null;
    state.selectedEmailId = null;
    state.mailboxDetailOnMobile = false;
    state.calendarWeekOffset = 0;
    showToast('Demo data reset');
    await Promise.all([loadInfo(), renderPage()]);
  } catch {
    showToast('Demo data could not be reset', 'error');
  }
};

document.querySelector('#primary-nav').addEventListener('click', (event) => {
  const target = event.target.closest('[data-page]');
  if (target) {
    void setPage(target.dataset.page);
  }
});

pageElement.addEventListener('click', async (event) => {
  const target = event.target.closest('[data-action]');
  if (!target) {
    return;
  }
  const { action, resource, id, relationshipId, relationshipKind } = target.dataset;
  if (action === 'retry') {
    await renderPage();
  }
  if (action === 'add-record') {
    await openRecordDialog(resource, null, relationshipId ?? null, relationshipKind ?? null);
  }
  if (action === 'edit-record') {
    try {
      const record = await findRecord(resource, id);
      await openRecordDialog(resource, record, relationshipId ?? null);
    } catch {
      showToast('Record could not be opened', 'error');
    }
  }
  if (action === 'delete-record') {
    await deleteRecord(resource, id);
  }
  if (action === 'open-record') {
    await openDetail(resource, id);
  }
  if (action === 'open-calendar-event') {
    await openDetail(resource, id, 'calendar');
  }
  if (action === 'select-email') {
    state.selectedEmailId = id;
    state.mailboxDetailOnMobile = true;
    await renderPage(false);
    const focusTarget = window.matchMedia('(max-width: 820px)').matches
      ? document.querySelector('.mailbox-back')
      : document.querySelector(
          `[data-action="select-email"][data-id="${CSS.escape(state.selectedEmailId)}"]`,
        );
    focusTarget?.focus({ preventScroll: true });
  }
  if (action === 'back-to-messages') {
    state.mailboxDetailOnMobile = false;
    await renderPage(false);
    document
      .querySelector(
        `[data-action="select-email"][data-id="${CSS.escape(state.selectedEmailId ?? '')}"]`,
      )
      ?.focus({ preventScroll: true });
  }
  if (action === 'change-week') {
    state.calendarWeekOffset += Number(target.dataset.weekDelta);
    await renderPage(false);
  }
  if (action === 'this-week') {
    state.calendarWeekOffset = 0;
    await renderPage(false);
  }
  if (action === 'back-to-list') {
    state.detail = null;
    await renderPage();
    workspaceElement.focus({ preventScroll: true });
    moveToTop();
  }
  if (action === 'import-message') {
    await openImportDialog();
  }
});

pageElement.addEventListener('input', (event) => {
  const filter = event.target.dataset.filter;
  if (!filter) {
    return;
  }
  state.filters = {
    ...state.filters,
    [filter]: event.target.value,
  };
  void renderPage(false).then(() => {
    const input = document.querySelector(`[data-filter="${filter}"]`);
    if (input) {
      input.focus();
      input.setSelectionRange(input.value.length, input.value.length);
    }
  });
});

recordForm.addEventListener('submit', (event) => {
  event.preventDefault();
  void submitRecordForm();
});

document.querySelector('#dialog-close').addEventListener('click', () => recordDialog.close());
document.querySelector('#dialog-cancel').addEventListener('click', () => recordDialog.close());
document.querySelector('#reset-button').addEventListener('click', () => void resetData());

void loadInfo().catch(() => {
  showToast('Snapshot date unavailable', 'error');
});
void renderPage();
