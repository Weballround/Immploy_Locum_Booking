import { useEffect, useRef, useState } from 'react'
import './App.css'
import immployLogo from './assets/immploy-logo.png'

type Shift = {
  id: number
  site_id: number
  profession_id: number
  client_name: string
  site_name: string
  profession_name: string
  starts_at: string
  ends_at: string
  pay_rate?: string
  bill_rate?: string
  status: 'open' | 'booked' | 'completed' | 'cancelled'
  notes: string
  confirmed_booking?: {
    id: number
    candidate_id: number
    candidate_name: string
    status: 'confirmed'
  } | null
}

type Candidate = {
  id: number
  full_name: string
  compliance_status: string
  role_name?: string
  home_area?: string
  home_region?: string
  worked_at_facility?: boolean
  facility_shift_count?: number
  last_worked_on?: string | null
  proximity_label?: string
  eligibility_reasons?: string[]
  profession_names?: string[]
  directory_result?: boolean
}

type SessionPayload = {
  authenticated?: boolean
  booking_time_step_seconds?: number
  mfa_enabled?: boolean
  mfa_required?: boolean
  access_rules?: { link_conf?: boolean } | null
  permissions?: {
    manage_bookings?: boolean
    manage_candidates?: boolean
    send_booking_sms?: boolean
    view_candidate_pay_rates?: boolean
    view_client_charge_rates?: boolean
    override_approved_rates?: boolean
  }
}

type BookingSms = {
  id?: number
  status: 'not_queued' | 'queued' | 'processing' | 'accepted' | 'failed'
  body: string
  destination: string
}

type ShiftCreationOptions = {
  sites: { id: number; name: string; client_name: string }[]
  professions: { id: number; name: string; legacy_mysql_id?: number | null }[]
}

type CandidateLocationOption = {
  region: string
  areas: string[]
}

type CandidateCreationOptions = {
  professions: ShiftCreationOptions['professions']
  locations: CandidateLocationOption[]
  profile?: CandidateProfileOptions
}

type CandidateProfileOption = {
  id: number | string
  label: string
  parent_id?: number | null
}

type CandidateProfileOptions = {
  countries: CandidateProfileOption[]
  visa_types: CandidateProfileOption[]
  languages: CandidateProfileOption[]
  divisions: CandidateProfileOption[]
  consultants: CandidateProfileOption[]
  employment_equity: CandidateProfileOption[]
  education_levels: CandidateProfileOption[]
  qualifications: CandidateProfileOption[]
  qualification_types: CandidateProfileOption[]
  sources: CandidateProfileOption[]
  marital_statuses: CandidateProfileOption[]
  drivers_licenses: CandidateProfileOption[]
  fingerprint_statuses: CandidateProfileOption[]
  criminal_checks: CandidateProfileOption[]
  sexes: CandidateProfileOption[]
}

type CandidateProfile = DirectoryCandidate & {
  preferred_name: string
  date_of_birth: string | null
  identity_number: string
  is_sa_id: boolean
  passport_number: string
  visa_type: string
  visa_start: string | null
  visa_end: string | null
  visa_selected: boolean
  country_of_origin: string
  nationality: string
  home_language: string
  is_locum: boolean
  is_permanent: boolean
  home_phone: string
  other_contact: string
  physical_address: string
  note: string
  division: string
  assigned_consultant: string
  sex: string
  sex_source: string
  citizenship_status: string
  employment_equity: string
  is_disabled: boolean
  fingerprint_status: string
  criminal_check: string
  drivers_license: string
  owns_car: boolean
  qualification: string
  qualification_types: string[]
  education_level: string
  source: string
  marital_status: string
  other_languages: string[]
  can_set_compliance: boolean
}

type SiteOption = ShiftCreationOptions['sites'][number]

type VacancyCreationResponse = {
  id: number
  reference: string
  shifts: Shift[]
}

type SiteRoleOption = {
  id: number
  name: string
  pay_rate?: string
  bill_rate?: string
}

type DirectoryCandidate = {
  id: number
  first_name?: string
  last_name?: string
  full_name: string
  email?: string
  phone?: string
  compliance_status: string
  home_area: string
  home_region: string
  postal_code?: string
  is_active?: boolean
  profession_names: string[]
  profession_ids?: number[]
  worked_at_facility?: boolean
  facility_shift_count?: number
  last_worked_on?: string | null
  proximity_label?: string
}

type BookingResponse = {
  id: number
  shift: number
  candidate: number
  status: 'confirmed'
}

type BookNowResponse = {
  vacancy: VacancyCreationResponse
  booking: BookingResponse
}

type ActiveView = 'bookings' | 'candidates' | 'clients' | 'reports' | 'security'

type MfaSetup = {
  qr_code_data_url: string
}

const emptyShiftForm = {
  reference: '',
  site: '',
  profession: '',
  pay_rate: '',
  notes: '',
  shift_items: [{ starts_at: '', ends_at: '' }],
}

const emptyCandidateForm = {
  first_name: '',
  last_name: '',
  home_area: '',
  home_region: 'Western Cape',
  profession: '',
}

const emptyCandidateEditForm = {
  first_name: '',
  last_name: '',
  preferred_name: '',
  date_of_birth: '',
  identity_number: '',
  is_sa_id: false,
  passport_number: '',
  visa_type: '',
  visa_start: '',
  visa_end: '',
  visa_selected: false,
  country_of_origin: '',
  nationality: '',
  home_language: '',
  is_locum: false,
  is_permanent: false,
  email: '',
  phone: '',
  home_phone: '',
  other_contact: '',
  physical_address: '',
  home_area: '',
  home_region: '',
  postal_code: '',
  note: '',
  division: '',
  assigned_consultant: '',
  sex: '',
  citizenship_status: '',
  employment_equity: '',
  is_disabled: false,
  fingerprint_status: '',
  criminal_check: '',
  drivers_license: '',
  owns_car: false,
  qualification: '',
  qualification_types: [] as string[],
  education_level: '',
  source: '',
  marital_status: '',
  other_languages: [] as string[],
  is_active: true,
  profession_ids: [] as number[],
}

const emptyCandidateProfileOptions: CandidateProfileOptions = {
  countries: [], visa_types: [], languages: [], divisions: [], consultants: [],
  employment_equity: [], education_levels: [], qualifications: [],
  qualification_types: [], sources: [], marital_statuses: [], drivers_licenses: [],
  fingerprint_statuses: [], criminal_checks: [], sexes: [],
}

const emptyCandidateShiftForm = {
  reference: '',
  site: '',
  profession: '',
  notes: '',
  shift_items: [{ starts_at: '', ends_at: '' }],
}

const statusLabel: Record<Shift['status'], string> = {
  open: 'Open',
  booked: 'Booked',
  completed: 'Completed',
  cancelled: 'Cancelled',
}

function candidateRegionOptions(locations: CandidateLocationOption[], currentRegion = '') {
  return Array.from(new Set([
    ...locations.map((location) => location.region),
    ...(currentRegion ? [currentRegion] : []),
  ])).sort((left, right) => left.localeCompare(right))
}

function candidateAreaOptions(
  locations: CandidateLocationOption[],
  region: string,
  currentArea = '',
) {
  const configuredAreas = locations.find((location) => location.region === region)?.areas ?? []
  return Array.from(new Set([
    ...configuredAreas,
    ...(currentArea ? [currentArea] : []),
  ])).sort((left, right) => left.localeCompare(right))
}

function candidateProfileOptionLabels(options: CandidateProfileOption[], current = '') {
  return Array.from(new Set([
    ...options.map((option) => option.label),
    ...(current ? [current] : []),
  ])).sort((left, right) => left.localeCompare(right))
}

function candidateProfileOptionsWithHistorical(
  options: CandidateProfileOption[],
  current: string[],
) {
  const configured = new Set(options.map((option) => option.label))
  return [
    ...options,
    ...current
      .filter((label) => !configured.has(label))
      .map((label) => ({ id: `historical:${label}`, label })),
  ]
}

function candidateQualificationTypeOptions(
  options: CandidateProfileOption[],
  current: string[],
  professions: ShiftCreationOptions['professions'],
  selectedProfessionIds: number[],
) {
  const allowedLegacyIds = new Set(
    professions
      .filter((profession) => selectedProfessionIds.includes(profession.id))
      .map((profession) => profession.legacy_mysql_id)
      .filter((legacyId): legacyId is number => legacyId != null),
  )
  return candidateProfileOptionsWithHistorical(
    options.filter((option) => allowedLegacyIds.has(Number(option.id))),
    current,
  )
}

function CandidateSelectField({
  label,
  value,
  options,
  onChange,
  disabled = false,
  hint = '',
}: {
  label: string
  value: string
  options: CandidateProfileOption[]
  onChange: (value: string) => void
  disabled?: boolean
  hint?: string
}) {
  return (
    <label>
      <span>{label}</span>
      <select aria-label={label} value={value} onChange={(event) => onChange(event.target.value)} disabled={disabled}>
        <option value="">Select {label.toLowerCase()}</option>
        {candidateProfileOptionLabels(options, value).map((option) => (
          <option key={option} value={option}>{option}</option>
        ))}
      </select>
      {hint && <small className="field-hint">{hint}</small>}
    </label>
  )
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat('en-ZA', {
    timeZone: 'Africa/Johannesburg',
    weekday: 'short',
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

const JOHANNESBURG_TIME_ZONE = 'Africa/Johannesburg'
const DEFAULT_BOOKING_TIME_STEP_SECONDS = 15 * 60
const DEFAULT_SHIFT_DURATION_HOURS = 7

function johannesburgParts(value: string | Date) {
  const parts = new Intl.DateTimeFormat('en-ZA', {
    timeZone: JOHANNESBURG_TIME_ZONE,
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(typeof value === 'string' ? new Date(value) : value)
  return Object.fromEntries(parts.map((part) => [part.type, part.value]))
}

function johannesburgDateKey(value: string | Date) {
  const parts = johannesburgParts(value)
  return `${parts.year}-${parts.month}-${parts.day}`
}

function johannesburgMonthKey(value: string | Date) {
  return johannesburgDateKey(value).slice(0, 7)
}

function currentMonthKey() {
  return johannesburgMonthKey(new Date())
}

function moveMonth(monthKey: string, amount: number) {
  const [year, month] = monthKey.split('-').map(Number)
  const moved = new Date(Date.UTC(year, month - 1 + amount, 1))
  return `${moved.getUTCFullYear()}-${String(moved.getUTCMonth() + 1).padStart(2, '0')}`
}

function calendarDates(monthKey: string) {
  const [year, month] = monthKey.split('-').map(Number)
  const first = new Date(Date.UTC(year, month - 1, 1))
  const mondayOffset = (first.getUTCDay() + 6) % 7
  return Array.from({ length: 42 }, (_, index) => {
    const date = new Date(Date.UTC(year, month - 1, 1 - mondayOffset + index))
    return date.toISOString().slice(0, 10)
  })
}

function calendarQueryBounds(monthKey: string) {
  return {
    startsBefore: `${moveMonth(monthKey, 1)}-01T00:00:00+02:00`,
    endsAfter: `${monthKey}-01T00:00:00+02:00`,
  }
}

function formatCalendarShiftTime(shift: Shift) {
  const starts = johannesburgParts(shift.starts_at)
  const ends = johannesburgParts(shift.ends_at)
  const startTime = `${starts.hour}:${starts.minute}`
  const endTime = `${ends.hour}:${ends.minute}`
  if (johannesburgDateKey(shift.starts_at) === johannesburgDateKey(shift.ends_at)) {
    return `${startTime} – ${endTime}`
  }
  const endMonth = new Intl.DateTimeFormat('en-ZA', {
    month: 'short', timeZone: JOHANNESBURG_TIME_ZONE,
  }).format(new Date(shift.ends_at))
  return `${startTime} – ${Number(ends.day)} ${endMonth}, ${endTime}`
}

function addHoursToLocalDateTime(value: string, hours: number) {
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/)
  if (!match) return ''
  const [, year, month, day, hour, minute] = match.map(Number)
  const result = new Date(Date.UTC(year, month - 1, day, hour + hours, minute))
  return `${result.getUTCFullYear()}-${String(result.getUTCMonth() + 1).padStart(2, '0')}-${String(result.getUTCDate()).padStart(2, '0')}T${String(result.getUTCHours()).padStart(2, '0')}:${String(result.getUTCMinutes()).padStart(2, '0')}`
}

function getCookie(name: string) {
  const prefix = `${name}=`
  return document.cookie
    .split(';')
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix))
    ?.slice(prefix.length)
}

function firstApiError(value: unknown): string | null {
  if (typeof value === 'string') return value
  if (Array.isArray(value)) {
    for (const item of value) {
      const message = firstApiError(item)
      if (message) return message
    }
  }
  if (value && typeof value === 'object') {
    for (const item of Object.values(value)) {
      const message = firstApiError(item)
      if (message) return message
    }
  }
  return null
}

function App() {
  const [activeView, setActiveView] = useState<ActiveView>('bookings')
  const [shifts, setShifts] = useState<Shift[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [authRequired, setAuthRequired] = useState(true)
  const [authenticated, setAuthenticated] = useState(false)
  const [signingOut, setSigningOut] = useState(false)
  const [selectedShift, setSelectedShift] = useState<Shift | null>(null)
  const [candidates, setCandidates] = useState<Candidate[]>([])
  const [candidateSearch, setCandidateSearch] = useState('')
  const [candidateLoading, setCandidateLoading] = useState(false)
  const [candidateError, setCandidateError] = useState('')
  const [candidateActionError, setCandidateActionError] = useState('')
  const [candidateSource, setCandidateSource] = useState<'eligible' | 'directory'>('eligible')
  const [confirmingCandidateId, setConfirmingCandidateId] = useState<number | null>(null)
  const [notice, setNotice] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [mfaRequired, setMfaRequired] = useState(false)
  const [mfaCode, setMfaCode] = useState('')
  const [signingIn, setSigningIn] = useState(false)
  const [csrfReady, setCsrfReady] = useState(false)
  const [loginError, setLoginError] = useState('')
  const [mfaEnabled, setMfaEnabled] = useState(false)
  const [mfaSetup, setMfaSetup] = useState<MfaSetup | null>(null)
  const [mfaSetupCode, setMfaSetupCode] = useState('')
  const [mfaPassword, setMfaPassword] = useState('')
  const [mfaLoading, setMfaLoading] = useState(false)
  const [mfaSaving, setMfaSaving] = useState(false)
  const [mfaError, setMfaError] = useState('')
  const [canManageBookings, setCanManageBookings] = useState(false)
  const [canManageCandidates, setCanManageCandidates] = useState(false)
  const [canViewCandidatePayRates, setCanViewCandidatePayRates] = useState(false)
  const [canViewClientChargeRates, setCanViewClientChargeRates] = useState(false)
  const [canOverrideApprovedRates, setCanOverrideApprovedRates] = useState(false)
  const [bookingTimeStepSeconds, setBookingTimeStepSeconds] = useState(
    DEFAULT_BOOKING_TIME_STEP_SECONDS,
  )
  const [canSendBookingSms, setCanSendBookingSms] = useState(false)
  const [bookingSms, setBookingSms] = useState<BookingSms | null>(null)
  const [bookingSmsLoading, setBookingSmsLoading] = useState(false)
  const [bookingSmsSending, setBookingSmsSending] = useState(false)
  const [bookingSmsError, setBookingSmsError] = useState('')
  const [bookingSmsReload, setBookingSmsReload] = useState(0)
  const [shiftFormOpen, setShiftFormOpen] = useState(false)
  const [shiftOptions, setShiftOptions] = useState<ShiftCreationOptions>({
    sites: [],
    professions: [],
  })
  const [candidateLocations, setCandidateLocations] = useState<CandidateLocationOption[]>([])
  const [candidateOptionsLoaded, setCandidateOptionsLoaded] = useState(false)
  const [shiftOptionsLoading, setShiftOptionsLoading] = useState(false)
  const [shiftSaving, setShiftSaving] = useState(false)
  const [shiftFormError, setShiftFormError] = useState('')
  const [shiftForm, setShiftForm] = useState(emptyShiftForm)
  const [siteRoleOptions, setSiteRoleOptions] = useState<SiteRoleOption[]>([])
  const [roleOptionsLoading, setRoleOptionsLoading] = useState(false)
  const [roleOptionsError, setRoleOptionsError] = useState('')
  const [roleOptionsReload, setRoleOptionsReload] = useState(0)
  const [bookNowFacility, setBookNowFacility] = useState<SiteOption | null>(null)
  const [bookNowCandidates, setBookNowCandidates] = useState<DirectoryCandidate[]>([])
  const [bookNowCandidateId, setBookNowCandidateId] = useState('')
  const [bookNowCandidateLoading, setBookNowCandidateLoading] = useState(false)
  const [bookNowCandidateError, setBookNowCandidateError] = useState('')
  const [bookNowCandidateReload, setBookNowCandidateReload] = useState(0)
  const [candidateFormOpen, setCandidateFormOpen] = useState(false)
  const [candidateForm, setCandidateForm] = useState(emptyCandidateForm)
  const [candidateSaving, setCandidateSaving] = useState(false)
  const [candidateFormError, setCandidateFormError] = useState('')
  const [candidateEdit, setCandidateEdit] = useState<DirectoryCandidate | null>(null)
  const [candidateEditProfile, setCandidateEditProfile] = useState<CandidateProfile | null>(null)
  const [candidateEditForm, setCandidateEditForm] = useState(emptyCandidateEditForm)
  const [candidateEditTab, setCandidateEditTab] = useState<'general' | 'general2'>('general')
  const [candidateProfileOptions, setCandidateProfileOptions] = useState(emptyCandidateProfileOptions)
  const [candidateEditSaving, setCandidateEditSaving] = useState(false)
  const [candidateEditError, setCandidateEditError] = useState('')
  const [directoryCandidates, setDirectoryCandidates] = useState<DirectoryCandidate[]>([])
  const [directoryLoading, setDirectoryLoading] = useState(false)
  const [directoryError, setDirectoryError] = useState('')
  const [facilityError, setFacilityError] = useState('')
  const [facilitySearch, setFacilitySearch] = useState('')
  const [facilityDirectorySearch, setFacilityDirectorySearch] = useState('')
  const [directorySearch, setDirectorySearch] = useState('')
  const [facilityDisplay, setFacilityDisplay] = useState<'directory' | 'calendar'>('directory')
  const [selectedFacilityId, setSelectedFacilityId] = useState('')
  const [calendarMonth, setCalendarMonth] = useState(currentMonthKey)
  const [calendarShifts, setCalendarShifts] = useState<Shift[]>([])
  const [calendarLoading, setCalendarLoading] = useState(false)
  const [calendarError, setCalendarError] = useState('')
  const [calendarFocusDate, setCalendarFocusDate] = useState('')
  const [calendarReload, setCalendarReload] = useState(0)
  const [batchCandidate, setBatchCandidate] = useState<DirectoryCandidate | null>(null)
  const [batchFacility, setBatchFacility] = useState<SiteOption | null>(null)
  const [batchShifts, setBatchShifts] = useState<Shift[]>([])
  const [batchAssignments, setBatchAssignments] = useState<Record<number, number>>({})
  const [batchCandidatesByShift, setBatchCandidatesByShift] = useState<Record<number, Candidate[]>>({})
  const [batchLoading, setBatchLoading] = useState(false)
  const [batchSaving, setBatchSaving] = useState(false)
  const [batchError, setBatchError] = useState('')
  const [batchCreatingNew, setBatchCreatingNew] = useState(false)
  const [batchCreationLoading, setBatchCreationLoading] = useState(false)
  const [batchCreationForm, setBatchCreationForm] = useState(emptyCandidateShiftForm)
  const [batchCreationRoles, setBatchCreationRoles] = useState<SiteRoleOption[]>([])
  const [batchCreationFailure, setBatchCreationFailure] = useState<'options' | 'roles' | null>(null)
  const candidateRequestId = useRef(0)
  const batchRequestId = useRef(0)
  const roleRequestId = useRef(0)
  const bookNowCandidateRequestId = useRef(0)
  const authEpoch = useRef(0)
  const candidateProfileRequestId = useRef(0)
  const candidateIdentityRequestId = useRef(0)
  const candidateEditIdRef = useRef<number | null>(null)
  const calendarRequestId = useRef(0)
  const bookingSmsRequestId = useRef(0)
  const calendarGridRef = useRef<HTMLDivElement>(null)
  const confirmationPending = useRef(false)
  const bookingSmsPending = useRef(false)
  const vacancyCreationPending = useRef(false)
  const candidateFormDialogRef = useRef<HTMLElement>(null)
  const candidateEditDialogRef = useRef<HTMLElement>(null)
  const vacancyDialogRef = useRef<HTMLElement>(null)
  const candidateFinderDialogRef = useRef<HTMLElement>(null)
  const batchDialogRef = useRef<HTMLElement>(null)
  const selectedShiftId = selectedShift?.id ?? null

  useEffect(() => {
    const dialog = candidateEdit
      ? candidateEditDialogRef.current
      : candidateFormOpen
        ? candidateFormDialogRef.current
        : shiftFormOpen
        ? vacancyDialogRef.current
        : batchCandidate || batchFacility
          ? batchDialogRef.current
          : selectedShiftId !== null
            ? candidateFinderDialogRef.current
            : null
    if (!dialog) return

    const previouslyFocused = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null
    const focusableSelector = [
      'button:not([disabled])',
      'input:not([disabled])',
      'select:not([disabled])',
      'textarea:not([disabled])',
      'a[href]',
      '[tabindex]:not([tabindex="-1"])',
    ].join(',')
    const getFocusable = () => Array.from(
      dialog.querySelectorAll<HTMLElement>(focusableSelector),
    ).filter((element) => element.getAttribute('aria-hidden') !== 'true')
    const initialFocus = dialog.querySelector<HTMLElement>('[data-dialog-initial-focus]')
      ?? getFocusable()[0]
      ?? dialog
    initialFocus.focus()

    const handleDialogKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        const closeButton = dialog.querySelector<HTMLButtonElement>('[data-dialog-close]')
        if (closeButton && !closeButton.disabled) {
          event.preventDefault()
          closeButton.click()
        }
        return
      }
      if (event.key !== 'Tab') return
      const focusable = getFocusable()
      if (focusable.length === 0) {
        event.preventDefault()
        dialog.focus()
        return
      }
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      const activeElement = document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null
      if (!activeElement || !focusable.includes(activeElement)) {
        event.preventDefault()
        ;(event.shiftKey ? last : first).focus()
      } else if (event.shiftKey && activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', handleDialogKeyDown)
    return () => {
      document.removeEventListener('keydown', handleDialogKeyDown)
      if (previouslyFocused && document.contains(previouslyFocused)) {
        previouslyFocused.focus()
      }
    }
  }, [batchCandidate, batchCreatingNew, batchFacility, batchLoading, candidateEdit, candidateFormOpen, candidateLoading, selectedShiftId, shiftFormOpen, shiftOptionsLoading])

  function clearSensitiveState() {
    authEpoch.current += 1
    candidateRequestId.current += 1
    batchRequestId.current += 1
    roleRequestId.current += 1
    bookNowCandidateRequestId.current += 1
    calendarRequestId.current += 1
    bookingSmsRequestId.current += 1
    confirmationPending.current = false
    bookingSmsPending.current = false
    vacancyCreationPending.current = false
    setActiveView('bookings')
    setLoading(false)
    setShifts([])
    setError('')
    setSelectedShift(null)
    setCandidates([])
    setCandidateSearch('')
    setCandidateLoading(false)
    setCandidateError('')
    setCandidateActionError('')
    setCandidateSource('eligible')
    setConfirmingCandidateId(null)
    setNotice('')
    setUsername('')
    setPassword('')
    setMfaRequired(false)
    setMfaCode('')
    setSigningIn(false)
    setSigningOut(false)
    setCsrfReady(false)
    setLoginError('')
    setMfaEnabled(false)
    setMfaSetup(null)
    setMfaSetupCode('')
    setMfaPassword('')
    setMfaLoading(false)
    setMfaSaving(false)
    setMfaError('')
    setCanManageBookings(false)
    setCanManageCandidates(false)
    setCanViewCandidatePayRates(false)
    setCanViewClientChargeRates(false)
    setCanOverrideApprovedRates(false)
    setBookingTimeStepSeconds(DEFAULT_BOOKING_TIME_STEP_SECONDS)
    setCanSendBookingSms(false)
    setBookingSms(null)
    setBookingSmsLoading(false)
    setBookingSmsSending(false)
    setBookingSmsError('')
    setBookingSmsReload(0)
    setShiftFormOpen(false)
    setShiftOptions({ sites: [], professions: [] })
    setCandidateLocations([])
    setCandidateOptionsLoaded(false)
    setShiftOptionsLoading(false)
    setShiftSaving(false)
    setShiftFormError('')
    setShiftForm(emptyShiftForm)
    setSiteRoleOptions([])
    setRoleOptionsLoading(false)
    setRoleOptionsError('')
    setRoleOptionsReload(0)
    setBookNowFacility(null)
    setBookNowCandidates([])
    setBookNowCandidateId('')
    setBookNowCandidateLoading(false)
    setBookNowCandidateError('')
    setBookNowCandidateReload(0)
    setCandidateFormOpen(false)
    setCandidateForm(emptyCandidateForm)
    setCandidateSaving(false)
    setCandidateFormError('')
    candidateProfileRequestId.current += 1
    candidateIdentityRequestId.current += 1
    candidateEditIdRef.current = null
    setCandidateEdit(null)
    setCandidateEditForm(emptyCandidateEditForm)
    setCandidateEditSaving(false)
    setCandidateEditError('')
    setDirectoryCandidates([])
    setDirectoryLoading(false)
    setDirectoryError('')
    setFacilityError('')
    setFacilitySearch('')
    setFacilityDirectorySearch('')
    setDirectorySearch('')
    setFacilityDisplay('directory')
    setSelectedFacilityId('')
    setCalendarMonth(currentMonthKey())
    setCalendarShifts([])
    setCalendarLoading(false)
    setCalendarError('')
    setCalendarFocusDate('')
    setCalendarReload(0)
    setBatchCandidate(null)
    setBatchFacility(null)
    setBatchShifts([])
    setBatchAssignments({})
    setBatchCandidatesByShift({})
    setBatchLoading(false)
    setBatchSaving(false)
    setBatchError('')
    setBatchCreatingNew(false)
    setBatchCreationLoading(false)
    setBatchCreationForm(emptyCandidateShiftForm)
    setBatchCreationRoles([])
    setBatchCreationFailure(null)
    setAuthenticated(false)
  }

  function requireAuthentication() {
    clearSensitiveState()
    setAuthRequired(true)
  }

  async function reconcileSessionAfterForbidden(requestEpoch: number) {
    try {
      const response = await fetch('/api/session/', { credentials: 'same-origin' })
      if (requestEpoch !== authEpoch.current) return
      if (response.status === 401) {
        requireAuthentication()
        return
      }
      if (!response.ok) return
      const payload = await response.json() as SessionPayload
      if (requestEpoch !== authEpoch.current) return
      if (payload.authenticated !== true) {
        requireAuthentication()
        return
      }
      applySessionAccess(payload)
    } catch {
      // A failed reconciliation is not proof that the authenticated session ended.
    }
  }

  function handleAuthorizationLoss(response: Response) {
    if (response.status === 401) {
      requireAuthentication()
      return true
    }
    if (response.status === 403) {
      void reconcileSessionAfterForbidden(authEpoch.current)
    }
    return false
  }

  function restartPasswordSignIn(message = '') {
    setMfaRequired(false)
    setMfaCode('')
    setPassword('')
    setLoginError(message)
  }

  async function signOut() {
    if (signingOut) return
    const requestEpoch = authEpoch.current
    setSigningOut(true)
    try {
      const csrfToken = getCookie('csrftoken')
      const response = await fetch('/api/session/', {
        method: 'DELETE',
        credentials: 'same-origin',
        headers: csrfToken ? { 'X-CSRFToken': csrfToken } : {},
      })
      if (requestEpoch !== authEpoch.current) return
      if (response.status === 401) {
        requireAuthentication()
        return
      }
      if (!response.ok) {
        await loadSessionAccess()
        if (requestEpoch !== authEpoch.current) return
        throw new Error('Could not sign out')
      }
      requireAuthentication()
    } catch (reason) {
      if (requestEpoch === authEpoch.current) {
        setError((reason as Error).message)
      }
    } finally {
      if (requestEpoch === authEpoch.current) {
        setSigningOut(false)
      }
    }
  }

  async function loadShifts() {
    const requestEpoch = authEpoch.current
    setLoading(true)
    setError('')
    try {
      const response = await fetch('/api/shifts/', { credentials: 'same-origin' })
      if (requestEpoch !== authEpoch.current) return
      if (handleAuthorizationLoss(response)) return
      if (!response.ok) throw new Error('Could not load shifts')
      const payload = await response.json() as Shift[]
      if (requestEpoch !== authEpoch.current) return
      setShifts(payload)
      setAuthRequired(false)
    } catch (reason) {
      if (requestEpoch === authEpoch.current) setError((reason as Error).message)
    } finally {
      if (requestEpoch === authEpoch.current) setLoading(false)
    }
  }

  function applySessionAccess(payload: SessionPayload) {
    setAuthenticated(Boolean(payload.authenticated))
    if (payload.authenticated) {
      setCanManageBookings(Boolean(payload.permissions?.manage_bookings))
      setCanManageCandidates(Boolean(payload.permissions?.manage_candidates))
      setCanViewCandidatePayRates(Boolean(payload.permissions?.view_candidate_pay_rates))
      setCanViewClientChargeRates(Boolean(payload.permissions?.view_client_charge_rates))
      setCanOverrideApprovedRates(Boolean(payload.permissions?.override_approved_rates))
      setBookingTimeStepSeconds(
        payload.booking_time_step_seconds === 60
          ? 60
          : DEFAULT_BOOKING_TIME_STEP_SECONDS,
      )
      setCanSendBookingSms(Boolean(payload.permissions?.send_booking_sms))
      setMfaEnabled(Boolean(payload.mfa_enabled))
    }
  }

  async function loadAuthorizedLanding(payload: SessionPayload) {
    const canBook = Boolean(payload.permissions?.manage_bookings)
    const canEditCandidates = Boolean(payload.permissions?.manage_candidates)
    setAuthRequired(false)
    if (canBook) {
      setActiveView('bookings')
      await loadShifts()
    } else if (canEditCandidates) {
      setActiveView('candidates')
      setLoading(false)
      await loadDirectoryCandidates()
    } else {
      setLoading(false)
    }
  }

  async function loadSessionAccess() {
    const requestEpoch = authEpoch.current
    try {
      const response = await fetch('/api/session/', { credentials: 'same-origin' })
      if (requestEpoch !== authEpoch.current) return
      if (handleAuthorizationLoss(response)) return
      if (response.ok) {
        const payload = await response.json() as SessionPayload
        if (requestEpoch !== authEpoch.current) return
        if (payload.authenticated !== true) {
          requireAuthentication()
          setCsrfReady(true)
          return
        }
        applySessionAccess(payload)
        await loadAuthorizedLanding(payload)
      }
    } catch {
      // Shift/API authorization remains authoritative when session metadata is unavailable.
    }
  }

  useEffect(() => {
    void loadSessionAccess()
  }, [])

  useEffect(() => {
    const bookingId = selectedShift?.confirmed_booking?.id
    bookingSmsRequestId.current += 1
    setBookingSms(null)
    setBookingSmsError('')
    setBookingSmsSending(false)
    bookingSmsPending.current = false
    if (!canSendBookingSms || !bookingId) {
      setBookingSmsLoading(false)
      return
    }
    const requestId = bookingSmsRequestId.current
    const requestEpoch = authEpoch.current
    setBookingSmsLoading(true)
    fetch(`/api/bookings/${bookingId}/confirmation-sms/`, {
      credentials: 'same-origin',
    })
      .then(async (response) => {
        if (requestEpoch !== authEpoch.current || requestId !== bookingSmsRequestId.current) return null
        if (handleAuthorizationLoss(response)) return null
        if (!response.ok) {
          const payload = typeof response.json === 'function'
            ? await response.json().catch(() => null) as unknown
            : null
          if (requestEpoch !== authEpoch.current || requestId !== bookingSmsRequestId.current) return null
          throw new Error(firstApiError(payload) || 'Could not load booking SMS')
        }
        const payload = await response.json() as BookingSms
        if (requestEpoch !== authEpoch.current || requestId !== bookingSmsRequestId.current) return null
        return payload
      })
      .then((payload) => {
        if (payload && requestEpoch === authEpoch.current && requestId === bookingSmsRequestId.current) {
          setBookingSms(payload)
        }
      })
      .catch((reason) => {
        if (requestEpoch === authEpoch.current && requestId === bookingSmsRequestId.current) {
          setBookingSmsError((reason as Error).message)
        }
      })
      .finally(() => {
        if (requestEpoch === authEpoch.current && requestId === bookingSmsRequestId.current) {
          setBookingSmsLoading(false)
        }
      })
  }, [bookingSmsReload, canSendBookingSms, selectedShift?.confirmed_booking?.id])

  useEffect(() => {
    if (!authRequired) return
    let cancelled = false
    setCsrfReady(false)
    setLoginError('')
    fetch('/api/session/', { credentials: 'same-origin' })
      .then((response) => {
        if (!response.ok) throw new Error('Could not prepare secure sign-in')
        if (!cancelled) setCsrfReady(true)
      })
      .catch(() => {
        if (!cancelled) setLoginError('Could not prepare secure sign-in. Refresh and try again.')
      })
    return () => { cancelled = true }
  }, [authRequired])

  useEffect(() => {
    if (!shiftFormOpen || !shiftForm.site) {
      roleRequestId.current += 1
      setRoleOptionsLoading(false)
      setSiteRoleOptions([])
      return
    }
    const requestId = ++roleRequestId.current
    const requestEpoch = authEpoch.current
    setRoleOptionsError('')
    setRoleOptionsLoading(true)
    fetch(`/api/vacancies/site-role-options/?site=${shiftForm.site}`, {
      credentials: 'same-origin',
    })
      .then((response) => {
        if (requestEpoch !== authEpoch.current || requestId !== roleRequestId.current) {
          return { professions: [] }
        }
        if (handleAuthorizationLoss(response)) return { professions: [] }
        if (!response.ok) throw new Error('Could not load facility roles')
        return response.json() as Promise<{ professions: SiteRoleOption[] }>
      })
      .then((payload) => {
        if (requestId === roleRequestId.current) {
          setSiteRoleOptions(payload.professions)
        }
      })
      .catch(() => {
        if (requestId === roleRequestId.current) {
          setSiteRoleOptions([])
          setRoleOptionsError('Could not load roles for this facility.')
        }
      })
      .finally(() => {
        if (requestId === roleRequestId.current) setRoleOptionsLoading(false)
      })
  }, [roleOptionsReload, shiftForm.site, shiftFormOpen])

  useEffect(() => {
    const shift = shiftForm.shift_items[0]
    if (
      !bookNowFacility
      || !shiftForm.profession
      || !shift.starts_at
      || !shift.ends_at
      || shift.ends_at <= shift.starts_at
    ) {
      bookNowCandidateRequestId.current += 1
      setBookNowCandidates([])
      setBookNowCandidateId('')
      setBookNowCandidateLoading(false)
      setBookNowCandidateError('')
      return
    }
    void loadBookNowCandidates(
      bookNowFacility.id,
      Number(shiftForm.profession),
      shift.starts_at,
      shift.ends_at,
    )
  }, [
    bookNowCandidateReload,
    bookNowFacility,
    shiftForm.profession,
    shiftForm.shift_items,
  ])

  useEffect(() => {
    if (
      authRequired
      || activeView !== 'clients'
      || facilityDisplay !== 'calendar'
      || !selectedFacilityId
    ) {
      calendarRequestId.current += 1
      return
    }
    const requestId = ++calendarRequestId.current
    const requestEpoch = authEpoch.current
    const bounds = calendarQueryBounds(calendarMonth)
    const params = new URLSearchParams({
      site: selectedFacilityId,
      starts_before: bounds.startsBefore,
      ends_after: bounds.endsAfter,
    })
    setCalendarLoading(true)
    setCalendarError('')
    setCalendarFocusDate(`${calendarMonth}-01`)
    fetch(`/api/shifts/?${params}`, { credentials: 'same-origin' })
      .then((response) => {
        if (requestEpoch !== authEpoch.current || requestId !== calendarRequestId.current) return []
        if (handleAuthorizationLoss(response)) return []
        if (!response.ok) throw new Error('Could not load the Facility calendar')
        return response.json() as Promise<Shift[]>
      })
      .then((payload) => {
        if (requestEpoch === authEpoch.current && requestId === calendarRequestId.current) {
          setCalendarShifts(payload)
        }
      })
      .catch((reason) => {
        if (requestEpoch === authEpoch.current && requestId === calendarRequestId.current) {
          setCalendarShifts([])
          setCalendarError((reason as Error).message)
        }
      })
      .finally(() => {
        if (requestEpoch === authEpoch.current && requestId === calendarRequestId.current) {
          setCalendarLoading(false)
        }
      })
  }, [activeView, authRequired, calendarMonth, calendarReload, facilityDisplay, selectedFacilityId])

  async function signIn(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSigningIn(true)
    setLoginError('')
    try {
      const csrfToken = getCookie('csrftoken')
      const response = await fetch('/api/session/', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          ...(csrfToken ? { 'X-CSRFToken': csrfToken } : {}),
        },
        body: JSON.stringify(
          mfaRequired ? { mfa_code: mfaCode } : { username, password },
        ),
      })
      const responsePayload = typeof response.json === 'function'
        ? await response.json().catch(() => null) as SessionPayload & { error?: string } | null
        : null
      if (response.status === 202 && responsePayload?.mfa_required) {
        setPassword('')
        setMfaRequired(true)
        setMfaCode('')
        return
      }
      if (!response.ok) {
        const result = responsePayload && typeof responsePayload === 'object'
          ? responsePayload
          : {}
        const message = result.error || 'Could not sign in'
        const normalizedMessage = message.toLocaleLowerCase()
        if (mfaRequired && (
          normalizedMessage.includes('challenge expired')
          || normalizedMessage.includes('start sign-in again')
        )) {
          restartPasswordSignIn(message)
          return
        }
        throw new Error(message)
      }
      if (responsePayload) {
        clearSensitiveState()
        applySessionAccess(responsePayload)
      }
      setPassword('')
      setMfaCode('')
      setMfaRequired(false)
      if (responsePayload) await loadAuthorizedLanding(responsePayload)
    } catch (reason) {
      setLoginError((reason as Error).message)
    } finally {
      setSigningIn(false)
    }
  }

  async function openShiftForm() {
    if (!canManageBookings) return
    const requestEpoch = authEpoch.current
    setShiftFormOpen(true)
    setShiftOptionsLoading(true)
    setShiftFormError('')
    setFacilitySearch('')
    try {
      const response = await fetch('/api/vacancies/creation-options/', {
        credentials: 'same-origin',
      })
      if (requestEpoch !== authEpoch.current) return
      if (handleAuthorizationLoss(response)) return
      if (!response.ok) throw new Error('Could not load shift options')
      const payload = await response.json() as ShiftCreationOptions
      if (requestEpoch !== authEpoch.current) return
      setShiftOptions(payload)
    } catch (reason) {
      if (requestEpoch === authEpoch.current) setShiftFormError((reason as Error).message)
    } finally {
      if (requestEpoch === authEpoch.current) setShiftOptionsLoading(false)
    }
  }

  async function openNewCandidateForm() {
    if (!canManageCandidates) return
    const requestEpoch = authEpoch.current
    setCandidateFormOpen(true)
    setCandidateFormError('')
    if (candidateOptionsLoaded) return
    setShiftOptionsLoading(true)
    try {
      const response = await fetch('/api/candidates/creation-options/', {
        credentials: 'same-origin',
      })
      if (requestEpoch !== authEpoch.current) return
      if (handleAuthorizationLoss(response)) return
      if (!response.ok) throw new Error('Could not load candidate roles and locations')
      const payload = await response.json() as CandidateCreationOptions
      if (requestEpoch !== authEpoch.current) return
      setShiftOptions((current) => ({ ...current, professions: payload.professions }))
      setCandidateLocations(payload.locations ?? [])
      setCandidateOptionsLoaded(true)
    } catch (reason) {
      if (requestEpoch === authEpoch.current) setCandidateFormError((reason as Error).message)
    } finally {
      if (requestEpoch === authEpoch.current) setShiftOptionsLoading(false)
    }
  }

  async function createCandidate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const requestEpoch = authEpoch.current
    setCandidateSaving(true)
    setCandidateFormError('')
    try {
      const csrfToken = getCookie('csrftoken')
      const response = await fetch('/api/candidates/', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          ...(csrfToken ? { 'X-CSRFToken': csrfToken } : {}),
        },
        body: JSON.stringify({
          first_name: candidateForm.first_name,
          last_name: candidateForm.last_name,
          home_area: candidateForm.home_area,
          home_region: candidateForm.home_region,
          profession_ids: [Number(candidateForm.profession)],
        }),
      })
      if (requestEpoch !== authEpoch.current) return
      if (handleAuthorizationLoss(response)) return
      if (!response.ok) throw new Error('Could not save candidate')
      const created = await response.json() as DirectoryCandidate
      if (requestEpoch !== authEpoch.current) return
      setDirectoryCandidates((current) => [...current, created].sort(
        (left, right) => left.full_name.localeCompare(right.full_name),
      ))
      setCandidateForm(emptyCandidateForm)
      setCandidateFormOpen(false)
      setNotice('Candidate added · pending compliance review')
    } catch (reason) {
      if (requestEpoch === authEpoch.current) setCandidateFormError((reason as Error).message)
    } finally {
      if (requestEpoch === authEpoch.current) setCandidateSaving(false)
    }
  }

  function closeCandidateEditor() {
    candidateProfileRequestId.current += 1
    candidateIdentityRequestId.current += 1
    candidateEditIdRef.current = null
    setCandidateEdit(null)
    setCandidateEditProfile(null)
    setCandidateEditForm(emptyCandidateEditForm)
    setCandidateEditError('')
    setCandidateEditSaving(false)
    setShiftOptionsLoading(false)
  }

  function handleCandidateProfileTabKey(event: React.KeyboardEvent<HTMLButtonElement>) {
    const tabs: Array<'general' | 'general2'> = ['general', 'general2']
    let nextIndex = tabs.indexOf(candidateEditTab)
    if (event.key === 'ArrowRight') nextIndex = (nextIndex + 1) % tabs.length
    else if (event.key === 'ArrowLeft') nextIndex = (nextIndex - 1 + tabs.length) % tabs.length
    else if (event.key === 'Home') nextIndex = 0
    else if (event.key === 'End') nextIndex = tabs.length - 1
    else return
    event.preventDefault()
    const nextTab = tabs[nextIndex]
    setCandidateEditTab(nextTab)
    document.getElementById(`candidate-${nextTab}-tab`)?.focus()
  }

  async function openCandidateEdit(candidate: DirectoryCandidate) {
    if (!canManageCandidates || candidateEditSaving) return
    const requestEpoch = authEpoch.current
    const profileRequestId = ++candidateProfileRequestId.current
    candidateIdentityRequestId.current += 1
    candidateEditIdRef.current = candidate.id
    setCandidateEdit(candidate)
    setCandidateEditProfile(null)
    setCandidateEditTab('general')
    setCandidateEditForm({
      ...emptyCandidateEditForm,
      first_name: candidate.first_name ?? candidate.full_name,
      last_name: candidate.last_name ?? '',
      email: candidate.email ?? '',
      phone: candidate.phone ?? '',
      home_area: candidate.home_area ?? '',
      home_region: candidate.home_region ?? '',
      postal_code: candidate.postal_code ?? '',
      is_active: candidate.is_active !== false,
      profession_ids: candidate.profession_ids ?? [],
    })
    setCandidateEditError('')
    setShiftOptionsLoading(true)
    try {
      const [profileResponse, optionsResponse] = await Promise.all([
        fetch(`/api/candidates/${candidate.id}/profile/`, { credentials: 'same-origin' }),
        fetch('/api/candidates/creation-options/', { credentials: 'same-origin' }),
      ])
      if (
        requestEpoch !== authEpoch.current
        || profileRequestId !== candidateProfileRequestId.current
        || candidateEditIdRef.current !== candidate.id
      ) return
      if (handleAuthorizationLoss(profileResponse) || handleAuthorizationLoss(optionsResponse)) return
      if (!profileResponse.ok || !optionsResponse.ok) {
        throw new Error('Could not load the Candidate profile and configured options')
      }
      const profile = await profileResponse.json() as CandidateProfile
      const payload = await optionsResponse.json() as CandidateCreationOptions
      if (
        requestEpoch !== authEpoch.current
        || profileRequestId !== candidateProfileRequestId.current
        || candidateEditIdRef.current !== candidate.id
      ) return
      setCandidateEditProfile(profile)
      setCandidateEditForm({
        first_name: profile.first_name ?? profile.full_name,
        last_name: profile.last_name ?? '',
        preferred_name: profile.preferred_name ?? '',
        date_of_birth: profile.date_of_birth ?? '',
        identity_number: profile.identity_number ?? '',
        is_sa_id: profile.is_sa_id,
        passport_number: profile.passport_number ?? '',
        visa_type: profile.visa_type ?? '',
        visa_start: profile.visa_start ?? '',
        visa_end: profile.visa_end ?? '',
        visa_selected: profile.visa_selected,
        country_of_origin: profile.country_of_origin ?? '',
        nationality: profile.nationality ?? '',
        home_language: profile.home_language ?? '',
        is_locum: profile.is_locum,
        is_permanent: profile.is_permanent,
        email: profile.email ?? '',
        phone: profile.phone ?? '',
        home_phone: profile.home_phone ?? '',
        other_contact: profile.other_contact ?? '',
        physical_address: profile.physical_address ?? '',
        home_area: profile.home_area ?? '',
        home_region: profile.home_region ?? '',
        postal_code: profile.postal_code ?? '',
        note: profile.note ?? '',
        division: profile.division ?? '',
        assigned_consultant: profile.assigned_consultant ?? '',
        sex: profile.sex ?? '',
        citizenship_status: profile.citizenship_status ?? '',
        employment_equity: profile.employment_equity ?? '',
        is_disabled: profile.is_disabled,
        fingerprint_status: profile.fingerprint_status ?? '',
        criminal_check: profile.criminal_check ?? '',
        drivers_license: profile.drivers_license ?? '',
        owns_car: profile.owns_car,
        qualification: profile.qualification ?? '',
        qualification_types: profile.qualification_types ?? [],
        education_level: profile.education_level ?? '',
        source: profile.source ?? '',
        marital_status: profile.marital_status ?? '',
        other_languages: profile.other_languages ?? [],
        is_active: profile.is_active !== false,
        profession_ids: profile.profession_ids ?? [],
      })
      setShiftOptions((current) => ({ ...current, professions: payload.professions }))
      setCandidateLocations(payload.locations ?? [])
      setCandidateProfileOptions(payload.profile ?? emptyCandidateProfileOptions)
      setCandidateOptionsLoaded(true)
    } catch (reason) {
      if (
        requestEpoch === authEpoch.current
        && profileRequestId === candidateProfileRequestId.current
        && candidateEditIdRef.current === candidate.id
      ) setCandidateEditError((reason as Error).message)
    } finally {
      if (
        requestEpoch === authEpoch.current
        && profileRequestId === candidateProfileRequestId.current
        && candidateEditIdRef.current === candidate.id
      ) setShiftOptionsLoading(false)
    }
  }

  async function saveCandidateEdit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!candidateEdit || candidateEditSaving) return
    const editingCandidateId = candidateEdit.id
    if (!candidateEditProfile) {
      setCandidateEditError('Candidate profile has not loaded. Close the form and try again.')
      return
    }
    const requestEpoch = authEpoch.current
    const profileRequestId = candidateProfileRequestId.current
    setCandidateEditSaving(true)
    setCandidateEditError('')
    try {
      const csrfToken = getCookie('csrftoken')
      const response = await fetch(`/api/candidates/${editingCandidateId}/profile/`, {
        method: 'PATCH',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          ...(csrfToken ? { 'X-CSRFToken': csrfToken } : {}),
        },
        body: JSON.stringify(candidateEditForm),
      })
      if (
        requestEpoch !== authEpoch.current
        || profileRequestId !== candidateProfileRequestId.current
        || candidateEditIdRef.current !== editingCandidateId
      ) return
      if (handleAuthorizationLoss(response)) return
      if (!response.ok) throw new Error('Could not update candidate')
      const updated = await response.json() as CandidateProfile
      if (
        requestEpoch !== authEpoch.current
        || profileRequestId !== candidateProfileRequestId.current
        || candidateEditIdRef.current !== editingCandidateId
      ) return
      setDirectoryCandidates((current) => (
        updated.is_active === false
          ? current.filter((candidate) => candidate.id !== editingCandidateId)
          : current.map((candidate) => (
            candidate.id === editingCandidateId ? updated : candidate
          )).sort((left, right) => left.full_name.localeCompare(right.full_name))
      ))
      closeCandidateEditor()
      setNotice('Candidate profile updated')
    } catch (reason) {
      if (
        requestEpoch === authEpoch.current
        && profileRequestId === candidateProfileRequestId.current
        && candidateEditIdRef.current === editingCandidateId
      ) setCandidateEditError((reason as Error).message)
    } finally {
      if (
        requestEpoch === authEpoch.current
        && profileRequestId === candidateProfileRequestId.current
        && candidateEditIdRef.current === editingCandidateId
      ) setCandidateEditSaving(false)
    }
  }

  async function decodeCandidateIdentity() {
    if (!candidateEditForm.is_sa_id || !candidateEditForm.identity_number || candidateEditSaving) return
    const requestEpoch = authEpoch.current
    const editingCandidateId = candidateEditIdRef.current
    if (editingCandidateId === null) return
    const submittedIdentity = candidateEditForm.identity_number
    const identityRequestId = ++candidateIdentityRequestId.current
    setCandidateEditError('')
    try {
      const csrfToken = getCookie('csrftoken')
      const response = await fetch('/api/candidates/decode-sa-id/', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          ...(csrfToken ? { 'X-CSRFToken': csrfToken } : {}),
        },
        body: JSON.stringify({ identity_number: submittedIdentity }),
      })
      if (
        requestEpoch !== authEpoch.current
        || identityRequestId !== candidateIdentityRequestId.current
        || candidateEditIdRef.current !== editingCandidateId
      ) return
      if (handleAuthorizationLoss(response)) return
      if (!response.ok) throw new Error('The South African ID is invalid or has an ambiguous birth date')
      const decoded = await response.json() as {
        date_of_birth: string
        sex: string
        sex_source: string
        citizenship_status: string
      }
      if (
        requestEpoch !== authEpoch.current
        || identityRequestId !== candidateIdentityRequestId.current
        || candidateEditIdRef.current !== editingCandidateId
      ) return
      setCandidateEditForm((current) => ({
        ...current,
        date_of_birth: decoded.date_of_birth,
        sex: decoded.sex,
        citizenship_status: decoded.citizenship_status,
      }))
      setCandidateEditProfile((current) => (
        current ? { ...current, sex_source: decoded.sex_source } : current
      ))
    } catch (reason) {
      if (
        requestEpoch === authEpoch.current
        && identityRequestId === candidateIdentityRequestId.current
        && candidateEditIdRef.current === editingCandidateId
      ) setCandidateEditError((reason as Error).message)
    }
  }

  async function loadDirectoryCandidates() {
    const requestEpoch = authEpoch.current
    setDirectoryLoading(true)
    setDirectoryError('')
    try {
      const response = await fetch('/api/candidates/', { credentials: 'same-origin' })
      if (requestEpoch !== authEpoch.current) return
      if (handleAuthorizationLoss(response)) return
      if (!response.ok) throw new Error('Could not load candidates')
      const payload = await response.json() as DirectoryCandidate[]
      if (requestEpoch !== authEpoch.current) return
      setDirectoryCandidates(payload)
    } catch (reason) {
      if (requestEpoch === authEpoch.current) setDirectoryError((reason as Error).message)
    } finally {
      if (requestEpoch === authEpoch.current) setDirectoryLoading(false)
    }
  }

  async function loadClientOptions(): Promise<ShiftCreationOptions | null> {
    const requestEpoch = authEpoch.current
    setShiftOptionsLoading(true)
    setFacilityError('')
    try {
      const response = await fetch('/api/vacancies/creation-options/', {
        credentials: 'same-origin',
      })
      if (requestEpoch !== authEpoch.current) return null
      if (handleAuthorizationLoss(response)) return null
      if (!response.ok) throw new Error('Could not load facilities')
      const payload = await response.json() as ShiftCreationOptions
      if (requestEpoch !== authEpoch.current) return null
      setShiftOptions(payload)
      return payload
    } catch (reason) {
      if (requestEpoch === authEpoch.current) setFacilityError((reason as Error).message)
      return null
    } finally {
      if (requestEpoch === authEpoch.current) setShiftOptionsLoading(false)
    }
  }

  async function loadMfaStatus() {
    const requestEpoch = authEpoch.current
    setMfaLoading(true)
    setMfaError('')
    try {
      const response = await fetch('/api/mfa/', { credentials: 'same-origin' })
      if (requestEpoch !== authEpoch.current) return
      if (handleAuthorizationLoss(response)) return
      if (!response.ok) throw new Error('Could not load sign-in security settings')
      const payload = await response.json() as { enabled: boolean }
      if (requestEpoch !== authEpoch.current) return
      setMfaEnabled(payload.enabled)
      setMfaSetup(null)
      setMfaSetupCode('')
    } catch (reason) {
      if (requestEpoch === authEpoch.current) setMfaError((reason as Error).message)
    } finally {
      if (requestEpoch === authEpoch.current) setMfaLoading(false)
    }
  }

  async function startMfaSetup(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const requestEpoch = authEpoch.current
    setMfaSaving(true)
    setMfaError('')
    try {
      const csrfToken = getCookie('csrftoken')
      const response = await fetch('/api/mfa/', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          ...(csrfToken ? { 'X-CSRFToken': csrfToken } : {}),
        },
        body: JSON.stringify({ password: mfaPassword }),
      })
      if (requestEpoch !== authEpoch.current) return
      if (handleAuthorizationLoss(response)) return
      if (!response.ok) throw new Error('Could not start Microsoft Authenticator setup')
      const payload = await response.json() as MfaSetup
      if (requestEpoch !== authEpoch.current) return
      setMfaSetup(payload)
      setMfaSetupCode('')
      setMfaPassword('')
    } catch (reason) {
      if (requestEpoch === authEpoch.current) setMfaError((reason as Error).message)
    } finally {
      if (requestEpoch === authEpoch.current) setMfaSaving(false)
    }
  }

  async function confirmMfaSetup(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const requestEpoch = authEpoch.current
    setMfaSaving(true)
    setMfaError('')
    try {
      const csrfToken = getCookie('csrftoken')
      const response = await fetch('/api/mfa/', {
        method: 'PUT',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          ...(csrfToken ? { 'X-CSRFToken': csrfToken } : {}),
        },
        body: JSON.stringify({ code: mfaSetupCode }),
      })
      if (requestEpoch !== authEpoch.current) return
      if (handleAuthorizationLoss(response)) return
      if (!response.ok) {
        const payload = await response.json().catch(() => null) as { error?: string } | null
        if (requestEpoch !== authEpoch.current) return
        const message = payload?.error || 'Could not enable MFA'
        if (message.endsWith('Start again.')) {
          setMfaSetup(null)
          setMfaSetupCode('')
          setMfaPassword('')
        }
        throw new Error(message)
      }
      if (requestEpoch !== authEpoch.current) return
      setMfaEnabled(true)
      setMfaSetup(null)
      setMfaSetupCode('')
    } catch (reason) {
      if (requestEpoch === authEpoch.current) setMfaError((reason as Error).message)
    } finally {
      if (requestEpoch === authEpoch.current) setMfaSaving(false)
    }
  }

  async function disableMfa(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const requestEpoch = authEpoch.current
    setMfaSaving(true)
    setMfaError('')
    try {
      const csrfToken = getCookie('csrftoken')
      const response = await fetch('/api/mfa/', {
        method: 'DELETE',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          ...(csrfToken ? { 'X-CSRFToken': csrfToken } : {}),
        },
        body: JSON.stringify({ code: mfaSetupCode }),
      })
      if (requestEpoch !== authEpoch.current) return
      if (handleAuthorizationLoss(response)) return
      if (!response.ok) {
        const payload = await response.json().catch(() => null) as { error?: string } | null
        if (requestEpoch !== authEpoch.current) return
        throw new Error(payload?.error || 'Could not disable MFA')
      }
      if (requestEpoch !== authEpoch.current) return
      requireAuthentication()
    } catch (reason) {
      if (requestEpoch === authEpoch.current) setMfaError((reason as Error).message)
    } finally {
      if (requestEpoch === authEpoch.current) setMfaSaving(false)
    }
  }

  function selectView(view: ActiveView) {
    if (authRequired) return
    if ((view === 'bookings' || view === 'clients' || view === 'reports') && !canManageBookings) return
    if (view === 'candidates' && !canManageBookings && !canManageCandidates) return
    setActiveView(view)
    if (view === 'candidates' && directoryCandidates.length === 0) {
      void loadDirectoryCandidates()
    }
    if (view === 'clients' && shiftOptions.sites.length === 0) {
      void loadClientOptions()
    }
    if (view === 'security') void loadMfaStatus()
  }

  function openFacilityCalendar(site: ShiftCreationOptions['sites'][number]) {
    setSelectedFacilityId(String(site.id))
    setFacilityDisplay('calendar')
    setCalendarShifts([])
    const firstShift = shifts
      .filter((shift) => shift.site_id === site.id)
      .sort((left, right) => left.starts_at.localeCompare(right.starts_at))[0]
    const month = firstShift ? johannesburgMonthKey(firstShift.starts_at) : currentMonthKey()
    setCalendarMonth(month)
    setCalendarFocusDate(`${month}-01`)
  }

  function openFacilityBookNow(site: SiteOption) {
    if (!canManageBookings) return
    bookNowCandidateRequestId.current += 1
    setBookNowFacility(site)
    setBookNowCandidates([])
    setBookNowCandidateId('')
    setBookNowCandidateLoading(false)
    setBookNowCandidateError('')
    setBookNowCandidateReload(0)
    setShiftForm({ ...emptyShiftForm, site: String(site.id) })
    setSiteRoleOptions([])
    setRoleOptionsError('')
    setShiftFormError('')
    setShiftOptionsLoading(false)
    setShiftFormOpen(true)
  }

  async function loadBookNowCandidates(
    siteId: number,
    professionId: number,
    startsAt: string,
    endsAt: string,
  ) {
    const requestId = ++bookNowCandidateRequestId.current
    const requestEpoch = authEpoch.current
    setBookNowCandidates([])
    setBookNowCandidateId('')
    setBookNowCandidateError('')
    setBookNowCandidateLoading(true)
    try {
      const parameters = new URLSearchParams({
        search: '',
        profession: String(professionId),
        site: String(siteId),
        starts_at: `${startsAt}:00`,
        ends_at: `${endsAt}:00`,
      })
      const response = await fetch(
        `/api/candidates/?${parameters.toString()}`,
        { credentials: 'same-origin' },
      )
      if (requestEpoch !== authEpoch.current || requestId !== bookNowCandidateRequestId.current) return
      if (handleAuthorizationLoss(response)) return
      if (!response.ok) throw new Error('Could not load matching candidates')
      const payload = await response.json() as DirectoryCandidate[]
      if (requestEpoch === authEpoch.current && requestId === bookNowCandidateRequestId.current) {
        setBookNowCandidates(payload)
      }
    } catch (reason) {
      if (requestEpoch === authEpoch.current && requestId === bookNowCandidateRequestId.current) {
        setBookNowCandidateError((reason as Error).message)
      }
    } finally {
      if (requestEpoch === authEpoch.current && requestId === bookNowCandidateRequestId.current) {
        setBookNowCandidateLoading(false)
      }
    }
  }

  async function retryFacilities() {
    const options = await loadClientOptions()
    if (facilityDisplay === 'calendar' && !selectedFacilityId && options?.sites[0]) {
      openFacilityCalendar(options.sites[0])
    }
  }

  async function openCalendarView() {
    if (authRequired) return
    setActiveView('clients')
    setFacilityDisplay('calendar')
    const options = shiftOptions.sites.length > 0 ? shiftOptions : await loadClientOptions()
    if (options?.sites[0]) openFacilityCalendar(options.sites[0])
  }

  function moveCalendarFocus(event: React.KeyboardEvent<HTMLDivElement>, date: string) {
    const currentIndex = facilityCalendarDates.indexOf(date)
    if (currentIndex < 0) return
    const offsets: Record<string, number> = {
      ArrowLeft: -1,
      ArrowRight: 1,
      ArrowUp: -7,
      ArrowDown: 7,
      Home: -(currentIndex % 7),
      End: 6 - (currentIndex % 7),
    }
    const offset = offsets[event.key]
    if (offset === undefined) return
    const targetDate = facilityCalendarDates[currentIndex + offset]
    if (!targetDate) return
    event.preventDefault()
    setCalendarFocusDate(targetDate)
    requestAnimationFrame(() => {
      calendarGridRef.current
        ?.querySelector<HTMLElement>(`[data-calendar-date="${targetDate}"]`)
        ?.focus()
    })
  }

  function closeShiftForm() {
    if (shiftSaving) return
    roleRequestId.current += 1
    bookNowCandidateRequestId.current += 1
    setShiftFormOpen(false)
    setBookNowFacility(null)
    setBookNowCandidates([])
    setBookNowCandidateId('')
    setBookNowCandidateLoading(false)
    setBookNowCandidateError('')
    setSiteRoleOptions([])
    setRoleOptionsError('')
    setShiftFormError('')
    setFacilitySearch('')
  }

  function addShiftItem() {
    setShiftFormError('')
    setShiftForm((current) => ({
      ...current,
      shift_items: [...current.shift_items, { starts_at: '', ends_at: '' }],
    }))
  }

  function updateShiftItem(index: number, field: 'starts_at' | 'ends_at', value: string) {
    setShiftFormError('')
    setShiftForm((current) => ({
      ...current,
      shift_items: current.shift_items.map((item, itemIndex) => (
        itemIndex === index
          ? {
              ...item,
              [field]: value,
              ...(field === 'starts_at'
                ? { ends_at: addHoursToLocalDateTime(value, DEFAULT_SHIFT_DURATION_HOURS) }
                : {}),
            }
          : item
      )),
    }))
  }

  function removeShiftItem(index: number) {
    setShiftFormError('')
    setShiftForm((current) => ({
      ...current,
      shift_items: current.shift_items.filter((_, itemIndex) => itemIndex !== index),
    }))
  }

  async function createShift(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (vacancyCreationPending.current) return
    const bookNowCandidate = bookNowCandidates.find(
      (candidate) => String(candidate.id) === bookNowCandidateId,
    )
    if (bookNowFacility && !bookNowCandidate) {
      setShiftFormError('Select a candidate to book.')
      return
    }
    if (shiftForm.shift_items.some((item) => item.ends_at <= item.starts_at)) {
      setShiftFormError('Every shift end must be after its start')
      return
    }
    vacancyCreationPending.current = true
    const requestEpoch = authEpoch.current
    setShiftSaving(true)
    setShiftFormError('')
    try {
      const csrfToken = getCookie('csrftoken')
      const response = await fetch(
        bookNowFacility ? '/api/vacancies/book-now/' : '/api/vacancies/',
        {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          ...(csrfToken ? { 'X-CSRFToken': csrfToken } : {}),
        },
        body: JSON.stringify(bookNowCandidate
          ? {
              reference: shiftForm.reference,
              site: Number(shiftForm.site),
              profession: Number(shiftForm.profession),
              notes: shiftForm.notes,
              candidate: bookNowCandidate.id,
              starts_at: `${shiftForm.shift_items[0].starts_at}:00`,
              ends_at: `${shiftForm.shift_items[0].ends_at}:00`,
            }
          : {
              reference: shiftForm.reference,
              site: Number(shiftForm.site),
              profession: Number(shiftForm.profession),
              notes: shiftForm.notes,
              shift_items: shiftForm.shift_items.map((item) => ({
                starts_at: `${item.starts_at}:00`,
                ends_at: `${item.ends_at}:00`,
                ...(
                  canViewCandidatePayRates
                  && canOverrideApprovedRates
                  && shiftForm.pay_rate
                    ? { pay_rate: shiftForm.pay_rate }
                    : {}
                ),
              })),
            }),
      })
      if (requestEpoch !== authEpoch.current) return
      if (handleAuthorizationLoss(response)) return
      if (!response.ok) {
        const payload = typeof response.json === 'function'
          ? await response.json().catch(() => null) as unknown
          : null
        throw new Error(firstApiError(payload) || 'Could not create vacancy')
      }
      const result = await response.json() as VacancyCreationResponse | BookNowResponse
      if (requestEpoch !== authEpoch.current) return
      const created = bookNowFacility
        ? (result as BookNowResponse).vacancy
        : result as VacancyCreationResponse
      setShifts((current) => [...current, ...created.shifts].sort(
        (left, right) => left.starts_at.localeCompare(right.starts_at),
      ))
      if (bookNowFacility && selectedFacilityId === String(bookNowFacility.id)) {
        setCalendarShifts((current) => [...current, ...created.shifts].sort(
          (left, right) => left.starts_at.localeCompare(right.starts_at),
        ))
      }
      setShiftForm(emptyShiftForm)
      setSiteRoleOptions([])
      setShiftFormOpen(false)
      setBookNowFacility(null)
      setBookNowCandidates([])
      setBookNowCandidateId('')
      setNotice(bookNowCandidate
        ? `Vacancy created and ${bookNowCandidate.full_name} booked`
        : `Vacancy created with ${created.shifts.length} ${created.shifts.length === 1 ? 'shift' : 'shifts'}`)
    } catch (reason) {
      if (requestEpoch !== authEpoch.current) return
      setShiftFormError((reason as Error).message)
    } finally {
      if (requestEpoch === authEpoch.current) {
        vacancyCreationPending.current = false
        setShiftSaving(false)
      }
    }
  }

  const openCount = shifts.filter((shift) => shift.status === 'open').length
  const bookedCount = shifts.filter((shift) => shift.status === 'booked').length
  const selectedFacility = shiftOptions.sites.find(
    (site) => String(site.id) === selectedFacilityId,
  ) ?? null
  const facilityCalendarShifts = calendarShifts
  const facilityCalendarDates = calendarDates(calendarMonth)
  const [calendarYear, calendarMonthNumber] = calendarMonth.split('-').map(Number)
  const calendarHeading = new Intl.DateTimeFormat('en-ZA', {
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(new Date(Date.UTC(calendarYear, calendarMonthNumber - 1, 1)))
  const filteredDirectoryCandidates = directoryCandidates.filter((candidate) => {
    const search = directorySearch.trim().toLocaleLowerCase()
    if (!search) return true
    return [candidate.full_name, candidate.home_area, candidate.home_region, ...candidate.profession_names]
      .some((value) => value.toLocaleLowerCase().includes(search))
  })
  const filteredFacilityDirectory = shiftOptions.sites.filter((site) => {
    const search = facilityDirectorySearch.trim().toLocaleLowerCase()
    if (!search) return true
    return `${site.client_name} ${site.name}`.toLocaleLowerCase().includes(search)
  })
  const displayedCandidates = candidates.filter((candidate) => {
    const search = candidateSearch.trim().toLocaleLowerCase()
    if (!search) return true
    return [candidate.full_name, candidate.home_area, candidate.home_region]
      .filter(Boolean)
      .some((value) => value?.toLocaleLowerCase().includes(search))
  })
  const filteredFacilityOptions = shiftOptions.sites.filter((site) => {
    if (String(site.id) === shiftForm.site) return true
    const search = facilitySearch.trim().toLocaleLowerCase()
    if (!search) return true
    return `${site.client_name} ${site.name}`.toLocaleLowerCase().includes(search)
  })

  async function openCandidateFinder(shift: Shift) {
    const requestId = ++candidateRequestId.current
    const requestEpoch = authEpoch.current
    setSelectedShift(shift)
    setCandidateLoading(true)
    setCandidateError('')
    setCandidateActionError('')
    setCandidateSource('eligible')
    setCandidates([])
    setCandidateSearch('')
    try {
      const response = await fetch(`/api/shifts/${shift.id}/candidates/`)
      if (requestEpoch !== authEpoch.current || requestId !== candidateRequestId.current) return
      if (handleAuthorizationLoss(response)) return
      if (!response.ok) throw new Error('Could not load eligible candidates')
      const result = await response.json() as Candidate[]
      if (requestId === candidateRequestId.current) setCandidates(result)
    } catch {
      if (requestId === candidateRequestId.current) {
        setCandidateError('Could not load eligible candidates')
      }
    } finally {
      if (requestId === candidateRequestId.current) setCandidateLoading(false)
    }
  }

  async function loadFullCandidateDirectory() {
    if (!selectedShift) return
    const requestId = ++candidateRequestId.current
    const requestEpoch = authEpoch.current
    setCandidateSource('directory')
    setCandidateLoading(true)
    setCandidateError('')
    setCandidateActionError('')
    setCandidates([])
    setCandidateSearch('')
    try {
      const response = await fetch(
        `/api/candidates/?search=&profession=${selectedShift.profession_id}`,
        { credentials: 'same-origin' },
      )
      if (requestEpoch !== authEpoch.current || requestId !== candidateRequestId.current) return
      if (handleAuthorizationLoss(response)) return
      if (!response.ok) throw new Error('Could not load the full candidate directory')
      const result = await response.json() as DirectoryCandidate[]
      if (requestEpoch !== authEpoch.current || requestId !== candidateRequestId.current) return
      setCandidates(result.map((candidate) => ({
        ...candidate,
        role_name: candidate.profession_names.join(', '),
        directory_result: true,
      })))
    } catch (reason) {
      if (requestEpoch === authEpoch.current && requestId === candidateRequestId.current) {
        setCandidateError((reason as Error).message)
      }
    } finally {
      if (requestEpoch === authEpoch.current && requestId === candidateRequestId.current) {
        setCandidateLoading(false)
      }
    }
  }

  async function confirmBooking(candidate: Candidate) {
    if (!selectedShift || !canManageBookings || confirmationPending.current) return
    const shiftId = selectedShift.id
    const requestEpoch = authEpoch.current
    confirmationPending.current = true
    setConfirmingCandidateId(candidate.id)
    setCandidateActionError('')
    try {
      const csrfToken = getCookie('csrftoken')
      const response = await fetch('/api/bookings/', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          ...(csrfToken ? { 'X-CSRFToken': csrfToken } : {}),
        },
        body: JSON.stringify({ shift: shiftId, candidate: candidate.id, status: 'confirmed' }),
      })
      if (requestEpoch !== authEpoch.current) return
      if (handleAuthorizationLoss(response)) return
      if (!response.ok) {
        const payload = typeof response.json === 'function'
          ? await response.json().catch(() => null) as unknown
          : null
        if (requestEpoch !== authEpoch.current) return
        throw new Error(firstApiError(payload) || 'Could not confirm booking')
      }
      const booking = await response.json() as Partial<BookingResponse>
      if (requestEpoch !== authEpoch.current) return
      const applyBooking = (current: Shift[]) => current.map((shift) => (
        shift.id === shiftId
          ? {
              ...shift,
              status: 'booked' as const,
              confirmed_booking: {
                id: typeof booking.id === 'number' ? booking.id : 0,
                candidate_id: candidate.id,
                candidate_name: candidate.full_name,
                status: 'confirmed' as const,
              },
            }
          : shift
      ))
      setShifts(applyBooking)
      setCalendarShifts(applyBooking)
      candidateRequestId.current += 1
      setSelectedShift(null)
      setNotice('Booking confirmed')
    } catch (reason) {
      if (requestEpoch === authEpoch.current) {
        setCandidateActionError((reason as Error).message)
      }
    } finally {
      if (requestEpoch === authEpoch.current) {
        confirmationPending.current = false
        setConfirmingCandidateId(null)
      }
    }
  }

  async function queueSelectedBookingSms() {
    const bookingId = selectedShift?.confirmed_booking?.id
    if (
      !canSendBookingSms
      || !bookingId
      || !bookingSms
      || bookingSms.status !== 'not_queued'
      || !bookingSms.body.trim()
      || bookingSmsPending.current
    ) return
    const requestEpoch = authEpoch.current
    const requestId = ++bookingSmsRequestId.current
    bookingSmsPending.current = true
    setBookingSmsSending(true)
    setBookingSmsError('')
    try {
      const csrfToken = getCookie('csrftoken')
      const response = await fetch(`/api/bookings/${bookingId}/confirmation-sms/`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          ...(csrfToken ? { 'X-CSRFToken': csrfToken } : {}),
        },
        body: JSON.stringify({ body: bookingSms.body.trim() }),
      })
      if (requestEpoch !== authEpoch.current || requestId !== bookingSmsRequestId.current) return
      if (handleAuthorizationLoss(response)) return
      if (!response.ok) {
        const payload = typeof response.json === 'function'
          ? await response.json().catch(() => null) as unknown
          : null
        if (requestEpoch !== authEpoch.current || requestId !== bookingSmsRequestId.current) return
        throw new Error(firstApiError(payload) || 'Could not queue booking SMS')
      }
      const payload = await response.json() as BookingSms
      if (requestEpoch !== authEpoch.current || requestId !== bookingSmsRequestId.current) return
      setBookingSms(payload)
    } catch (reason) {
      if (requestEpoch === authEpoch.current && requestId === bookingSmsRequestId.current) {
        setBookingSmsError((reason as Error).message)
      }
    } finally {
      if (requestEpoch === authEpoch.current && requestId === bookingSmsRequestId.current) {
        bookingSmsPending.current = false
        setBookingSmsSending(false)
      }
    }
  }

  function closeCandidateFinder() {
    if (confirmationPending.current || bookingSmsPending.current) return
    candidateRequestId.current += 1
    bookingSmsRequestId.current += 1
    setSelectedShift(null)
    setCandidates([])
    setCandidateSearch('')
    setCandidateError('')
    setCandidateActionError('')
    setCandidateSource('eligible')
    setCandidateLoading(false)
    setBookingSms(null)
    setBookingSmsLoading(false)
    setBookingSmsSending(false)
    setBookingSmsError('')
    setBookingSmsReload(0)
    bookingSmsPending.current = false
  }

  function closeBatchDialog() {
    if (batchSaving) return
    batchRequestId.current += 1
    setBatchCandidate(null)
    setBatchFacility(null)
    setBatchShifts([])
    setBatchAssignments({})
    setBatchCandidatesByShift({})
    setBatchLoading(false)
    setBatchError('')
    setBatchCreatingNew(false)
    setBatchCreationLoading(false)
    setBatchCreationForm(emptyCandidateShiftForm)
    setBatchCreationRoles([])
    setBatchCreationFailure(null)
  }

  async function openCandidateBatch(candidate: DirectoryCandidate) {
    const requestId = ++batchRequestId.current
    const requestEpoch = authEpoch.current
    setBatchCandidate(candidate)
    setBatchFacility(null)
    setBatchShifts([])
    setBatchAssignments({})
    setBatchCandidatesByShift({})
    setBatchLoading(true)
    setBatchSaving(false)
    setBatchError('')
    setBatchCreatingNew(false)
    setBatchCreationForm(emptyCandidateShiftForm)
    setBatchCreationRoles([])
    setBatchCreationFailure(null)
    try {
      const response = await fetch(`/api/candidates/${candidate.id}/compatible-shifts/`, {
        credentials: 'same-origin',
      })
      if (requestEpoch !== authEpoch.current || requestId !== batchRequestId.current) return
      if (handleAuthorizationLoss(response)) return
      if (!response.ok) throw new Error('Could not load compatible shifts')
      const result = await response.json() as Shift[]
      if (requestEpoch === authEpoch.current && requestId === batchRequestId.current) {
        setBatchShifts(result)
      }
    } catch (reason) {
      if (requestEpoch === authEpoch.current && requestId === batchRequestId.current) {
        setBatchError((reason as Error).message)
      }
    } finally {
      if (requestEpoch === authEpoch.current && requestId === batchRequestId.current) {
        setBatchLoading(false)
      }
    }
  }

  async function openCandidateShiftCreation() {
    if (!batchCandidate || batchSaving) return
    const requestId = ++batchRequestId.current
    const requestEpoch = authEpoch.current
    setBatchCreatingNew(true)
    setBatchCreationLoading(true)
    setBatchCreationForm(emptyCandidateShiftForm)
    setBatchCreationRoles([])
    setBatchCreationFailure(null)
    setBatchError('')
    try {
      const response = await fetch('/api/vacancies/creation-options/', { credentials: 'same-origin' })
      if (requestEpoch !== authEpoch.current || requestId !== batchRequestId.current) return
      if (handleAuthorizationLoss(response)) return
      if (!response.ok) throw new Error('Could not load Facilities')
      const result = await response.json() as ShiftCreationOptions
      if (requestEpoch !== authEpoch.current || requestId !== batchRequestId.current) return
      setShiftOptions(result)
    } catch (reason) {
      if (requestEpoch === authEpoch.current && requestId === batchRequestId.current) {
        setBatchCreationFailure('options')
        setBatchError((reason as Error).message)
      }
    } finally {
      if (requestEpoch === authEpoch.current && requestId === batchRequestId.current) {
        setBatchCreationLoading(false)
      }
    }
  }

  async function selectCandidateShiftFacility(site: string) {
    if (!batchCandidate || batchSaving) return
    const requestId = ++batchRequestId.current
    const requestEpoch = authEpoch.current
    setBatchCreationForm((current) => ({ ...current, site, profession: '' }))
    setBatchCreationRoles([])
    setBatchCreationFailure(null)
    setBatchError('')
    if (!site) return
    setBatchCreationLoading(true)
    try {
      const response = await fetch(`/api/vacancies/site-role-options/?site=${site}`, {
        credentials: 'same-origin',
      })
      if (requestEpoch !== authEpoch.current || requestId !== batchRequestId.current) return
      if (handleAuthorizationLoss(response)) return
      if (!response.ok) throw new Error('Could not load Facility roles')
      const result = await response.json() as { professions: SiteRoleOption[] }
      if (requestEpoch !== authEpoch.current || requestId !== batchRequestId.current) return
      const candidateProfessions = new Set(batchCandidate.profession_ids || [])
      setBatchCreationRoles(result.professions.filter((role) => candidateProfessions.has(role.id)))
    } catch (reason) {
      if (requestEpoch === authEpoch.current && requestId === batchRequestId.current) {
        setBatchCreationFailure('roles')
        setBatchError((reason as Error).message)
      }
    } finally {
      if (requestEpoch === authEpoch.current && requestId === batchRequestId.current) {
        setBatchCreationLoading(false)
      }
    }
  }

  async function submitCandidateShiftCreation(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!batchCandidate || batchSaving) return
    const requestId = batchRequestId.current
    const requestEpoch = authEpoch.current
    setBatchSaving(true)
    setBatchError('')
    try {
      const csrfToken = getCookie('csrftoken')
      const response = await fetch('/api/vacancies/book-candidate-shifts/', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          ...(csrfToken ? { 'X-CSRFToken': csrfToken } : {}),
        },
        body: JSON.stringify({
          candidate: batchCandidate.id,
          site: Number(batchCreationForm.site),
          profession: Number(batchCreationForm.profession),
          reference: batchCreationForm.reference,
          notes: batchCreationForm.notes,
          shift_items: batchCreationForm.shift_items,
        }),
      })
      if (requestEpoch !== authEpoch.current || requestId !== batchRequestId.current) return
      if (handleAuthorizationLoss(response)) return
      const result = typeof response.json === 'function' ? await response.json().catch(() => null) : null
      if (requestEpoch !== authEpoch.current || requestId !== batchRequestId.current) return
      if (!response.ok) throw new Error(firstApiError(result) || 'Could not create and book shifts')
      const created = result as { vacancy: VacancyCreationResponse; bookings: BookingResponse[] }
      setShifts((current) => [...current, ...created.vacancy.shifts].sort(
        (left, right) => left.starts_at.localeCompare(right.starts_at),
      ))
      setNotice(`${created.bookings.length} new ${created.bookings.length === 1 ? 'shift' : 'shifts'} booked for ${batchCandidate.full_name}`)
      closeBatchDialog()
    } catch (reason) {
      if (requestEpoch === authEpoch.current && requestId === batchRequestId.current) {
        setBatchError((reason as Error).message)
      }
    } finally {
      if (requestEpoch === authEpoch.current && requestId === batchRequestId.current) {
        setBatchSaving(false)
      }
    }
  }

  function toggleCandidateBatchShift(shiftId: number) {
    if (!batchCandidate || batchSaving) return
    setBatchAssignments((current) => {
      const next = { ...current }
      if (next[shiftId]) delete next[shiftId]
      else next[shiftId] = batchCandidate.id
      return next
    })
  }

  async function submitCandidateBatch() {
    if (!batchCandidate || batchSaving) return
    const assignments = batchShifts
      .filter((shift) => batchAssignments[shift.id] === batchCandidate.id)
      .map((shift) => ({ shift: shift.id, candidate: batchCandidate.id, status: 'confirmed' as const }))
    if (assignments.length === 0) {
      setBatchError('Select at least one shift.')
      return
    }
    await submitBatchAssignments(assignments, { [batchCandidate.id]: batchCandidate.full_name })
  }

  async function openFacilityBatch(facility: SiteOption) {
    const requestId = ++batchRequestId.current
    const requestEpoch = authEpoch.current
    const openShifts = facilityCalendarShifts.filter((shift) => shift.status === 'open')
    setBatchCandidate(null)
    setBatchFacility(facility)
    setBatchShifts(openShifts)
    setBatchAssignments({})
    setBatchCandidatesByShift({})
    setBatchLoading(openShifts.length > 0)
    setBatchSaving(false)
    setBatchError('')
    if (openShifts.length === 0) return

    try {
      const responses = await Promise.all(openShifts.map((shift) => fetch(
        `/api/shifts/${shift.id}/candidates/`,
        { credentials: 'same-origin' },
      )))
      if (requestEpoch !== authEpoch.current || requestId !== batchRequestId.current) return
      for (const response of responses) {
        if (handleAuthorizationLoss(response)) return
        if (!response.ok) throw new Error('Could not load eligible candidates')
      }
      const candidateLists = await Promise.all(
        responses.map((response) => response.json() as Promise<Candidate[]>),
      )
      if (requestEpoch !== authEpoch.current || requestId !== batchRequestId.current) return
      setBatchCandidatesByShift(Object.fromEntries(
        openShifts.map((shift, index) => [shift.id, candidateLists[index]]),
      ))
    } catch (reason) {
      if (requestEpoch === authEpoch.current && requestId === batchRequestId.current) {
        setBatchError((reason as Error).message)
      }
    } finally {
      if (requestEpoch === authEpoch.current && requestId === batchRequestId.current) {
        setBatchLoading(false)
      }
    }
  }

  function setFacilityBatchCandidate(shiftId: number, candidateId: string) {
    if (batchSaving) return
    setBatchAssignments((current) => {
      const next = { ...current }
      if (!candidateId) delete next[shiftId]
      else next[shiftId] = Number(candidateId)
      return next
    })
  }

  async function submitFacilityBatch() {
    if (!batchFacility || batchSaving) return
    const assignments = batchShifts
      .filter((shift) => batchAssignments[shift.id])
      .map((shift) => ({
        shift: shift.id,
        candidate: batchAssignments[shift.id],
        status: 'confirmed' as const,
      }))
    if (assignments.length === 0) {
      setBatchError('Select at least one candidate.')
      return
    }
    const candidateNames = Object.fromEntries(
      Object.values(batchCandidatesByShift).flat().map((candidate) => [candidate.id, candidate.full_name]),
    )
    await submitBatchAssignments(assignments, candidateNames)
  }

  async function submitBatchAssignments(
    assignments: { shift: number; candidate: number; status: 'confirmed' }[],
    candidateNames: Record<number, string>,
  ) {
    if (batchSaving) return

    const requestId = batchRequestId.current
    const requestEpoch = authEpoch.current
    setBatchSaving(true)
    setBatchError('')
    try {
      const csrfToken = getCookie('csrftoken')
      const response = await fetch('/api/bookings/bulk/', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          ...(csrfToken ? { 'X-CSRFToken': csrfToken } : {}),
        },
        body: JSON.stringify({ assignments }),
      })
      if (requestEpoch !== authEpoch.current || requestId !== batchRequestId.current) return
      if (handleAuthorizationLoss(response)) return
      if (!response.ok) {
        const payload = typeof response.json === 'function'
          ? await response.json().catch(() => null) as unknown
          : null
        if (requestEpoch !== authEpoch.current || requestId !== batchRequestId.current) return
        throw new Error(firstApiError(payload) || 'Could not create multiple bookings')
      }
      const bookings = await response.json() as BookingResponse[]
      if (requestEpoch !== authEpoch.current || requestId !== batchRequestId.current) return
      const bookingsByShift = new Map(bookings.map((booking) => [booking.shift, booking]))
      const applyBookings = (current: Shift[]) => current.map((shift) => {
        const booking = bookingsByShift.get(shift.id)
        if (!booking) return shift
        return {
          ...shift,
          status: 'booked' as const,
          confirmed_booking: {
            id: booking.id,
            candidate_id: booking.candidate,
            candidate_name: candidateNames[booking.candidate] || 'Confirmed candidate',
            status: 'confirmed' as const,
          },
        }
      })
      setShifts(applyBookings)
      setCalendarShifts(applyBookings)
      setBatchSaving(false)
      batchRequestId.current += 1
      setBatchCandidate(null)
      setBatchFacility(null)
      setBatchShifts([])
      setBatchAssignments({})
      setBatchCandidatesByShift({})
      setNotice(`${bookings.length} bookings confirmed`)
    } catch (reason) {
      if (requestEpoch === authEpoch.current && requestId === batchRequestId.current) {
        setBatchError((reason as Error).message)
      }
    } finally {
      if (requestEpoch === authEpoch.current && requestId === batchRequestId.current) {
        setBatchSaving(false)
      }
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand-mark" href="/" aria-label="IMMploy Recruitment">
          <img src={immployLogo} alt="IMMploy Recruitment" />
          <span>Locum operations</span>
        </a>
        <nav aria-label="Main navigation">
          {canManageBookings && <button className={`nav-button ${activeView === 'bookings' ? 'active' : ''}`} aria-label="Booking board" aria-pressed={activeView === 'bookings'} onClick={() => selectView('bookings')}><span>▦</span>Booking board</button>}
          {(canManageBookings || canManageCandidates) && <button className={`nav-button ${activeView === 'candidates' ? 'active' : ''}`} aria-label="Candidates" aria-pressed={activeView === 'candidates'} onClick={() => selectView('candidates')}><span>♙</span>Candidates</button>}
          {canManageBookings && <button className={`nav-button ${activeView === 'clients' ? 'active' : ''}`} aria-label="Clients" aria-pressed={activeView === 'clients'} onClick={() => selectView('clients')}><span>⌂</span>Facilities</button>}
          {canManageBookings && <button className={`nav-button ${activeView === 'reports' ? 'active' : ''}`} aria-label="Reports" aria-pressed={activeView === 'reports'} onClick={() => selectView('reports')}><span>↗</span>Coverage report</button>}
          <button className={`nav-button ${activeView === 'security' ? 'active' : ''}`} aria-label="Sign-in security" aria-pressed={activeView === 'security'} onClick={() => selectView('security')}><span>⌾</span>Sign-in security</button>
          {authenticated && (
            <button className="nav-button" aria-label="Sign out" disabled={signingOut} onClick={signOut}>
              <span>↪</span>{signingOut ? 'Signing out…' : 'Sign out'}
            </button>
          )}
        </nav>
        <div className="account-block">
          <div className="avatar">PB</div>
          <div><strong>Consultant</strong><span>IMMploy workforce</span></div>
        </div>
      </aside>

      <main>
        <header className="topbar">
          <div>
            <p className="eyebrow">IMMploy workforce</p>
            <h1>{
              activeView === 'bookings' ? 'Locum booking board'
                : activeView === 'candidates' ? 'Candidates'
                  : activeView === 'clients' ? 'Facilities'
                    : activeView === 'reports' ? 'Coverage report'
                      : 'Sign-in security'
            }</h1>
            <p className="subtitle">{
              activeView === 'bookings' ? 'Plan, match and confirm every shift from one place.'
                : activeView === 'candidates' ? 'Find active locums by name, role or area.'
                  : activeView === 'clients' ? 'Review facilities available for vacancy creation.'
                    : activeView === 'reports' ? 'See current placement coverage at a glance.'
                      : 'Protect your account with Microsoft Authenticator.'
            }</p>
          </div>
          {activeView === 'candidates' && canManageCandidates && (
            <button
              className="primary-button"
              aria-label="Add candidate"
              disabled={authRequired}
              onClick={openNewCandidateForm}
            >+ Add candidate</button>
          )}
        </header>

        {activeView === 'bookings' && <>
        <section className="summary-grid" aria-label="Booking summary">
          <article className="summary-card open-card">
            <span>Open shifts</span>
            <strong>{openCount}</strong>
            <small>Requires placement</small>
          </article>
          <article className="summary-card">
            <span>Booked</span>
            <strong>{bookedCount}</strong>
            <small>Confirmed placements</small>
          </article>
          <article className="summary-card">
            <span>Fill rate</span>
            <strong>{shifts.length ? `${Math.round((bookedCount / shifts.length) * 100)}%` : '—'}</strong>
            <small>Current schedule</small>
          </article>
        </section>

        <section className="board-panel">
          <div className="board-toolbar">
            <div>
              <h2>Upcoming shifts</h2>
              <p>{shifts.length} shifts in the current schedule</p>
            </div>
            <div className="view-switch" aria-label="View options">
              <button className="selected">List</button>
              <button onClick={() => void openCalendarView()}>Calendar</button>
            </div>
            <button
              className="primary-button"
              disabled={!canManageBookings || authRequired}
              onClick={openShiftForm}
            >+ Add vacancy</button>
          </div>

          {loading && <p className="state-message">Loading shifts…</p>}
          {authRequired ? (
            <div className="login-state">
              <div className="login-illustration" aria-hidden="true">
                <span>✓</span>
                <strong>Right role.</strong>
                <strong>Right facility.</strong>
                <strong>Right locum.</strong>
              </div>
              <form className="login-card" onSubmit={signIn}>
                <p className="eyebrow">Secure consultant access</p>
                <h2>{mfaRequired ? 'Verify with Microsoft Authenticator' : 'Sign in to IMMploy'}</h2>
                <p>{mfaRequired
                  ? 'Enter the six-digit code shown in Microsoft Authenticator.'
                  : 'Continue to automatic role and candidate matching.'}</p>
                {mfaRequired && (
                  <p className="login-trust-note">
                    On the trusted IMMploy LAN, this browser will remember MFA for 30 days.
                  </p>
                )}
                {!mfaRequired ? <>
                  <label>
                    <span>Username</span>
                    <input
                      autoFocus={username.length === 0}
                      autoComplete="username"
                      value={username}
                      onChange={(event) => setUsername(event.target.value)}
                      required
                    />
                  </label>
                  <label>
                    <span>Password</span>
                    <input
                      autoFocus={username.length > 0}
                      autoComplete="current-password"
                      type="password"
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                      required
                    />
                  </label>
                </> : (
                  <label>
                    <span>Authenticator code</span>
                    <input
                      autoFocus
                      autoComplete="one-time-code"
                      inputMode="numeric"
                      pattern="[0-9]{6}"
                      maxLength={6}
                      value={mfaCode}
                      onChange={(event) => setMfaCode(event.target.value.replace(/\D/g, ''))}
                      required
                    />
                  </label>
                )}
                {loginError && <p className="login-error" role="alert">{loginError}</p>}
                <button
                  type="submit"
                  className="primary-button login-button"
                  disabled={signingIn || !csrfReady}
                >
                  {signingIn ? 'Signing in…' : mfaRequired ? 'Verify code' : 'Sign in'}
                </button>
                {mfaRequired && (
                  <button
                    type="button"
                    className="login-back-button"
                    disabled={signingIn}
                    onClick={() => restartPasswordSignIn()}
                  >Back to password sign-in</button>
                )}
              </form>
            </div>
          ) : error && (
            <div className="state-action" role="alert">
              <p className="state-message error">{error}</p>
              <button className="secondary-button" onClick={() => void loadShifts()}>Retry shifts</button>
            </div>
          )}
          {!loading && !authRequired && !error && shifts.length === 0 && (
            <p className="state-message">No shifts yet. Create the first shift to get started.</p>
          )}

          <div className="shift-list">
            {shifts.map((shift) => (
              <article className="shift-card" key={shift.id}>
                <div className={`status-rail ${shift.status}`} />
                <div className="date-block">
                  <span>{new Intl.DateTimeFormat('en-ZA', {
                    month: 'short',
                    timeZone: JOHANNESBURG_TIME_ZONE,
                  }).format(new Date(shift.starts_at))}</span>
                  <strong>{new Intl.DateTimeFormat('en-ZA', {
                    day: 'numeric',
                    timeZone: JOHANNESBURG_TIME_ZONE,
                  }).format(new Date(shift.starts_at))}</strong>
                </div>
                <div className="shift-main">
                  <div className="shift-title-row">
                    <div>
                      <h3>{shift.client_name}</h3>
                      <p>{shift.site_name} · <span>{shift.profession_name}</span></p>
                    </div>
                    <span className={`status-pill ${shift.status}`}>{statusLabel[shift.status]}</span>
                  </div>
                  <div className="shift-meta">
                    <span>◷ {formatDate(shift.starts_at)} – {formatDate(shift.ends_at)}</span>
                    {canViewCandidatePayRates && shift.pay_rate && (
                      <span>R{shift.pay_rate}/hr pay</span>
                    )}
                    {canViewClientChargeRates && shift.bill_rate && (
                      <span>R{shift.bill_rate}/hr charge</span>
                    )}
                  </div>
                </div>
                <button
                  className="secondary-button"
                  disabled={shift.status === 'cancelled' || (shift.status !== 'open' && !shift.confirmed_booking)}
                  onClick={() => {
                    if (shift.status === 'open') {
                      void openCandidateFinder(shift)
                    } else {
                      setSelectedShift(shift)
                      setCandidates([])
                      setCandidateError('')
                    }
                  }}
                >
                  {shift.status === 'open' ? 'Add candidate' : 'View booking'}
                </button>
              </article>
            ))}
          </div>
        </section>
        </>}

        {activeView === 'candidates' && (
          <section className="directory-panel" aria-label="Candidate directory">
            <div className="directory-toolbar">
              <div>
                <h2>Active candidate directory</h2>
                <p>{directoryCandidates.length} candidates available for matching</p>
              </div>
              <label className="directory-search">
                <span>Search candidates</span>
                <input
                  type="search"
                  value={directorySearch}
                  onChange={(event) => setDirectorySearch(event.target.value)}
                  placeholder="Name, role or area"
                />
              </label>
            </div>
            {directoryLoading && <p className="state-message">Loading candidates…</p>}
            {directoryError && (
              <div className="state-action" role="alert">
                <p className="state-message error">{directoryError}</p>
                <button className="secondary-button" onClick={() => void loadDirectoryCandidates()}>Retry candidates</button>
              </div>
            )}
            {!directoryLoading && !directoryError && (
              <div className="directory-grid">
                {filteredDirectoryCandidates.map((candidate) => (
                  <article className="directory-card" key={candidate.id}>
                    <div className="candidate-initials">
                      {candidate.full_name.split(' ').map((part) => part[0]).join('').slice(0, 2)}
                    </div>
                    <div>
                      <strong>{candidate.full_name}</strong>
                      <p>{candidate.profession_names.join(', ') || 'No role assigned'}</p>
                      <small>{[candidate.home_area, candidate.home_region].filter(Boolean).join(' · ') || 'Area not recorded'}</small>
                    </div>
                    <div className="directory-card-actions">
                      <span className={`status-pill ${candidate.compliance_status === 'cleared' ? 'booked' : 'open'}`}>
                        {candidate.compliance_status}
                      </span>
                      {canManageCandidates && (
                        <button
                          className="secondary-button"
                          aria-label={`Edit ${candidate.full_name}`}
                          onClick={() => void openCandidateEdit(candidate)}
                        >Edit candidate</button>
                      )}
                      <button
                        className="secondary-button"
                        aria-label={`Book shifts for ${candidate.full_name}`}
                        disabled={!canManageBookings || candidate.compliance_status !== 'cleared'}
                        onClick={() => void openCandidateBatch(candidate)}
                      >Book shifts</button>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>
        )}

        {activeView === 'clients' && (
          <section className="directory-panel" aria-label="Facilities">
            <div className="directory-toolbar">
              <div>
                <h2>{facilityDisplay === 'calendar' ? 'Facility calendar' : 'Client facilities'}</h2>
                <p>{facilityDisplay === 'calendar'
                  ? 'Review open and confirmed shifts for one facility.'
                  : `${shiftOptions.sites.length} facilities ready for vacancy creation`}</p>
              </div>
              {facilityDisplay === 'calendar' && (
                <button className="secondary-button" onClick={() => setFacilityDisplay('directory')}>
                  All facilities
                </button>
              )}
              {facilityDisplay === 'directory' && (
                <label className="directory-search">
                  <span>Search facilities</span>
                  <input
                    type="search"
                    value={facilityDirectorySearch}
                    onChange={(event) => setFacilityDirectorySearch(event.target.value)}
                    placeholder="Client or Facility name"
                  />
                </label>
              )}
            </div>
            {shiftOptionsLoading && <p className="state-message">Loading facilities…</p>}
            {facilityError && (
              <div className="state-action" role="alert">
                <p className="state-message error">{facilityError}</p>
                <button className="secondary-button" onClick={() => void retryFacilities()}>Retry facilities</button>
              </div>
            )}
            {!shiftOptionsLoading && !facilityError && facilityDisplay === 'directory' && (
              <div className="facility-grid">
                {filteredFacilityDirectory.map((site) => (
                  <article className="facility-card" key={site.id}>
                    <span aria-hidden="true">⌂</span>
                    <div><strong>{site.client_name}</strong><p>{site.name}</p></div>
                    <div className="facility-card-actions">
                      <button
                        className="facility-book-now-button"
                        aria-label={`Book now for ${site.client_name} ${site.name}`}
                        disabled={!canManageBookings}
                        onClick={() => openFacilityBookNow(site)}
                      >Book now</button>
                      <button
                        className="facility-calendar-button"
                        aria-label={`View calendar for ${site.client_name} ${site.name}`}
                        onClick={() => openFacilityCalendar(site)}
                      >Calendar</button>
                    </div>
                  </article>
                ))}
              </div>
            )}
            {!shiftOptionsLoading && !facilityError && facilityDisplay === 'calendar' && selectedFacility && (
              <div className="facility-calendar">
                <div className="facility-calendar-toolbar">
                  <label>
                    <span>Facility</span>
                    <select
                      value={selectedFacilityId}
                      onChange={(event) => {
                        const site = shiftOptions.sites.find(
                          (option) => String(option.id) === event.target.value,
                        )
                        if (site) openFacilityCalendar(site)
                      }}
                    >
                      {shiftOptions.sites.map((site) => (
                        <option key={site.id} value={site.id}>{site.client_name} · {site.name}</option>
                      ))}
                    </select>
                  </label>
                  {!calendarLoading && (
                    <button
                      className="primary-button"
                      aria-label={`Multiple booking for ${selectedFacility.client_name} ${selectedFacility.name}`}
                      disabled={!canManageBookings || facilityCalendarShifts.every((shift) => shift.status !== 'open')}
                      onClick={() => void openFacilityBatch(selectedFacility)}
                    >Multiple booking</button>
                  )}
                  <div className="calendar-month-navigation">
                    <button className="secondary-button" aria-label="Previous month" onClick={() => setCalendarMonth((month) => moveMonth(month, -1))}>‹</button>
                    <h2>{calendarHeading}</h2>
                    <button className="secondary-button" aria-label="Next month" onClick={() => setCalendarMonth((month) => moveMonth(month, 1))}>›</button>
                  </div>
                </div>
                <div
                  className="facility-calendar-grid"
                  role="grid"
                  ref={calendarGridRef}
                  aria-busy={calendarLoading}
                  aria-label={`${selectedFacility.client_name} ${selectedFacility.name} calendar`}
                >
                  <div className="calendar-weekdays" role="row">
                    {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((weekday) => (
                      <span role="columnheader" key={weekday}>{weekday}</span>
                    ))}
                  </div>
                  <div className="calendar-days" role="rowgroup">
                    {Array.from({ length: 6 }, (_, weekIndex) => (
                      <div className="calendar-week" role="row" key={facilityCalendarDates[weekIndex * 7]}>
                    {facilityCalendarDates.slice(weekIndex * 7, weekIndex * 7 + 7).map((date) => {
                      const dayShifts = facilityCalendarShifts.filter(
                        (shift) => johannesburgDateKey(shift.starts_at) === date,
                      )
                      const dateValue = new Date(`${date}T00:00:00Z`)
                      const dateLabel = new Intl.DateTimeFormat('en-ZA', {
                        weekday: 'long', day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC',
                      }).format(dateValue)
                      return (
                        <div
                          className={`calendar-day ${date.startsWith(calendarMonth) ? '' : 'outside-month'}`}
                          role="gridcell"
                          aria-label={dateLabel}
                          data-calendar-date={date}
                          tabIndex={date === calendarFocusDate ? 0 : -1}
                          onKeyDown={(event) => moveCalendarFocus(event, date)}
                          key={date}
                        >
                          <span className="calendar-day-number">{dateValue.getUTCDate()}</span>
                          <div className="calendar-day-shifts">
                            {dayShifts.map((shift) => (
                              <button
                                className={`calendar-shift ${shift.status}`}
                                key={shift.id}
                                disabled={shift.status === 'cancelled' || (shift.status !== 'open' && !shift.confirmed_booking)}
                                aria-label={`${statusLabel[shift.status]} ${shift.profession_name} shift on ${dateLabel}, ${formatCalendarShiftTime(shift)}. ${shift.status === 'open' ? 'Add candidate' : shift.confirmed_booking ? 'Open booking details' : 'Unavailable'}`}
                                onClick={() => {
                                  if (shift.status === 'open') {
                                    void openCandidateFinder(shift)
                                  } else {
                                    setSelectedShift(shift)
                                    setCandidates([])
                                    setCandidateError('')
                                  }
                                }}
                              >
                                <strong>{shift.profession_name}</strong>
                                <span className="calendar-shift-status">{statusLabel[shift.status]}</span>
                                <span>{formatCalendarShiftTime(shift)}</span>
                              </button>
                            ))}
                          </div>
                        </div>
                      )
                    })}
                      </div>
                    ))}
                  </div>
                </div>
                {calendarLoading && <p className="state-message">Loading Facility calendar…</p>}
                {calendarError && (
                  <div className="state-action" role="alert">
                    <p className="state-message error">{calendarError}</p>
                    <button className="secondary-button" onClick={() => setCalendarReload((current) => current + 1)}>Retry calendar</button>
                  </div>
                )}
                {!calendarLoading && !calendarError && facilityCalendarShifts.length === 0 && (
                  <p className="state-message">No shifts are scheduled for this facility.</p>
                )}
              </div>
            )}
          </section>
        )}

        {activeView === 'reports' && (
          <>
            <section className="summary-grid" aria-label="Coverage summary">
              <article className="summary-card open-card"><span>Open shifts</span><strong>{openCount}</strong><small>Requires placement</small></article>
              <article className="summary-card"><span>Booked</span><strong>{bookedCount}</strong><small>Confirmed placements</small></article>
              <article className="summary-card"><span>Fill rate</span><strong>{shifts.length ? `${Math.round((bookedCount / shifts.length) * 100)}%` : '—'}</strong><small>Current schedule</small></article>
            </section>
            <section className="directory-panel report-note">
              <h2>Testing snapshot</h2>
              <p>This live operational view is calculated from the current booking schedule.</p>
            </section>
          </>
        )}

        {activeView === 'security' && (
          <section className="directory-panel security-panel" aria-label="Sign-in security settings">
            <div className="directory-toolbar">
              <div>
                <h2>Microsoft Authenticator</h2>
                <p>Use a rotating six-digit code as a second sign-in factor.</p>
              </div>
              <span className={`status-pill ${mfaEnabled ? 'booked' : 'open'}`}>
                {mfaEnabled ? 'Enabled' : 'Not enabled'}
              </span>
            </div>
            <div className="security-content">
              {mfaLoading ? <p className="state-message">Loading security settings…</p> : mfaEnabled ? (
                <>
                  <h3>Multi-factor authentication is enabled.</h3>
                  <p>Your password and a Microsoft Authenticator code are required at sign-in.</p>
                  <form className="security-form" onSubmit={disableMfa}>
                    <label>
                      <span>Current authenticator code</span>
                      <input
                        inputMode="numeric"
                        pattern="[0-9]{6}"
                        maxLength={6}
                        value={mfaSetupCode}
                        onChange={(event) => setMfaSetupCode(event.target.value.replace(/\D/g, ''))}
                        required
                      />
                    </label>
                    <button className="secondary-button" disabled={mfaSaving}>
                      {mfaSaving ? 'Disabling…' : 'Disable MFA'}
                    </button>
                  </form>
                </>
              ) : mfaSetup ? (
                <>
                  <h3>Scan this QR code</h3>
                  <p>Open Microsoft Authenticator, add an account, and choose “Other account”.</p>
                  <img className="mfa-qr" src={mfaSetup.qr_code_data_url} alt="Microsoft Authenticator setup QR code" />
                  <form className="security-form" onSubmit={confirmMfaSetup}>
                    <label>
                      <span>Authenticator code</span>
                      <input
                        autoComplete="one-time-code"
                        inputMode="numeric"
                        pattern="[0-9]{6}"
                        maxLength={6}
                        value={mfaSetupCode}
                        onChange={(event) => setMfaSetupCode(event.target.value.replace(/\D/g, ''))}
                        required
                      />
                    </label>
                    <button className="primary-button" disabled={mfaSaving}>
                      {mfaSaving ? 'Enabling…' : 'Enable MFA'}
                    </button>
                  </form>
                </>
              ) : (
                <>
                  <h3>Add a second sign-in factor</h3>
                  <p>Setup is optional until your rollout policy requires it.</p>
                  <form className="security-form" onSubmit={startMfaSetup}>
                    <label>
                      <span>Current password</span>
                      <input
                        type="password"
                        autoComplete="current-password"
                        value={mfaPassword}
                        onChange={(event) => setMfaPassword(event.target.value)}
                        required
                      />
                    </label>
                    <button className="primary-button" disabled={mfaSaving}>
                      {mfaSaving ? 'Preparing…' : 'Set up Microsoft Authenticator'}
                    </button>
                  </form>
                </>
              )}
              {mfaError && <p className="login-error" role="alert">{mfaError}</p>}
            </div>
          </section>
        )}
      </main>

      {candidateEdit && (
        <div className="modal-backdrop" role="presentation">
          <section
            ref={candidateEditDialogRef}
            className="shift-modal candidate-modal candidate-edit-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="edit-candidate-title"
            tabIndex={-1}
          >
            <div className="drawer-header">
              <div>
                <p className="eyebrow">Candidate directory</p>
                <h2 id="edit-candidate-title">Edit {candidateEdit.full_name}</h2>
                <p>Update booking contact details, matching location, status and roles.</p>
              </div>
              <button
                className="close-button"
                data-dialog-close
                aria-label="Close candidate editor"
                disabled={candidateEditSaving}
                onClick={closeCandidateEditor}
              >×</button>
            </div>
            <form className="shift-form candidate-edit-form" onSubmit={saveCandidateEdit}>
              <div className="candidate-profile-tabs full-width" role="tablist" aria-label="Candidate profile sections">
                <button
                  id="candidate-general-tab"
                  type="button"
                  role="tab"
                  aria-selected={candidateEditTab === 'general'}
                  aria-controls="candidate-general-panel"
                  tabIndex={candidateEditTab === 'general' ? 0 : -1}
                  className={candidateEditTab === 'general' ? 'active' : ''}
                  onClick={() => setCandidateEditTab('general')}
                  onKeyDown={handleCandidateProfileTabKey}
                >General</button>
                <button
                  id="candidate-general2-tab"
                  type="button"
                  role="tab"
                  aria-selected={candidateEditTab === 'general2'}
                  aria-controls="candidate-general2-panel"
                  tabIndex={candidateEditTab === 'general2' ? 0 : -1}
                  className={candidateEditTab === 'general2' ? 'active' : ''}
                  onClick={() => setCandidateEditTab('general2')}
                  onKeyDown={handleCandidateProfileTabKey}
                >General 2</button>
              </div>
              {candidateEditTab === 'general' && <div
                id="candidate-general-panel"
                className="candidate-profile-grid full-width"
                role="tabpanel"
                aria-labelledby="candidate-general-tab"
              >
              <div className="candidate-edit-section full-width">
                <div>
                  <span className="field-heading">Compliance status</span>
                  <output aria-label="Compliance status" className={`status-pill ${candidateEdit.compliance_status === 'cleared' ? 'booked' : 'open'}`}>
                    {candidateEdit.compliance_status === 'cleared' ? 'Cleared' : 'Pending'}
                  </output>
                </div>
                <label className="candidate-active-toggle">
                  <input
                    type="checkbox"
                    checked={candidateEditForm.is_active}
                    onChange={(event) => setCandidateEditForm({ ...candidateEditForm, is_active: event.target.checked })}
                    disabled={candidateEditSaving}
                  />
                  <span>Active candidate</span>
                </label>
              </div>
              <label>
                <span>First name</span>
                <input
                  data-dialog-initial-focus
                  value={candidateEditForm.first_name}
                  onChange={(event) => setCandidateEditForm({ ...candidateEditForm, first_name: event.target.value })}
                  disabled={candidateEditSaving}
                  required
                />
              </label>
              <label>
                <span>Last name</span>
                <input
                  value={candidateEditForm.last_name}
                  onChange={(event) => setCandidateEditForm({ ...candidateEditForm, last_name: event.target.value })}
                  disabled={candidateEditSaving}
                  required
                />
              </label>
              <label>
                <span>Preferred name</span>
                <input value={candidateEditForm.preferred_name} onChange={(event) => setCandidateEditForm({ ...candidateEditForm, preferred_name: event.target.value })} disabled={candidateEditSaving} />
              </label>
              <label className="candidate-active-toggle">
                <input
                  type="checkbox"
                  checked={candidateEditForm.is_sa_id}
                  onChange={(event) => {
                    const is_sa_id = event.target.checked
                    candidateIdentityRequestId.current += 1
                    setCandidateEditForm({ ...candidateEditForm, is_sa_id })
                    if (!is_sa_id) setCandidateEditProfile((current) => current ? { ...current, sex_source: '' } : current)
                  }}
                  disabled={candidateEditSaving}
                />
                <span>South African ID</span>
              </label>
              <label>
                <span>ID number</span>
                <input
                  inputMode="numeric"
                  autoComplete="off"
                  maxLength={13}
                  value={candidateEditForm.identity_number}
                  onChange={(event) => {
                    candidateIdentityRequestId.current += 1
                    setCandidateEditForm({
                      ...candidateEditForm,
                      identity_number: event.target.value.replace(/\D/g, '').slice(0, 13),
                    })
                  }}
                  onBlur={decodeCandidateIdentity}
                  disabled={candidateEditSaving}
                />
              </label>
              <label>
                <span>Date of birth</span>
                <input aria-label="Date of birth" type="date" value={candidateEditForm.date_of_birth} onChange={(event) => setCandidateEditForm({ ...candidateEditForm, date_of_birth: event.target.value })} disabled={candidateEditSaving || candidateEditForm.is_sa_id} />
                {candidateEditProfile?.sex_source === 'sa_id' && <small className="field-hint">Derived from validated South African ID</small>}
              </label>
              <label>
                <span>Passport number</span>
                <input value={candidateEditForm.passport_number} onChange={(event) => setCandidateEditForm({ ...candidateEditForm, passport_number: event.target.value })} disabled={candidateEditSaving} />
              </label>
              <label className="candidate-active-toggle">
                <input type="checkbox" checked={candidateEditForm.visa_selected} onChange={(event) => setCandidateEditForm({ ...candidateEditForm, visa_selected: event.target.checked })} disabled={candidateEditSaving} />
                <span>Visa selected</span>
              </label>
              <CandidateSelectField label="Visa type" value={candidateEditForm.visa_type} options={candidateProfileOptions.visa_types} onChange={(visa_type) => setCandidateEditForm({ ...candidateEditForm, visa_type })} disabled={candidateEditSaving || !candidateEditForm.visa_selected} />
              <label>
                <span>Visa start</span>
                <input type="date" value={candidateEditForm.visa_start} onChange={(event) => setCandidateEditForm({ ...candidateEditForm, visa_start: event.target.value })} disabled={candidateEditSaving || !candidateEditForm.visa_selected} />
              </label>
              <label>
                <span>Visa expiration</span>
                <input type="date" value={candidateEditForm.visa_end} onChange={(event) => setCandidateEditForm({ ...candidateEditForm, visa_end: event.target.value })} disabled={candidateEditSaving || !candidateEditForm.visa_selected} />
              </label>
              <label>
                <span>Email</span>
                <input
                  type="email"
                  value={candidateEditForm.email}
                  onChange={(event) => setCandidateEditForm({ ...candidateEditForm, email: event.target.value })}
                  disabled={candidateEditSaving}
                />
              </label>
              <label>
                <span>Cell phone</span>
                <input
                  type="tel"
                  value={candidateEditForm.phone}
                  onChange={(event) => setCandidateEditForm({ ...candidateEditForm, phone: event.target.value })}
                  disabled={candidateEditSaving}
                />
              </label>
              <label>
                <span>Home telephone</span>
                <input type="tel" value={candidateEditForm.home_phone} onChange={(event) => setCandidateEditForm({ ...candidateEditForm, home_phone: event.target.value })} disabled={candidateEditSaving} />
              </label>
              <label>
                <span>Other contact</span>
                <input value={candidateEditForm.other_contact} onChange={(event) => setCandidateEditForm({ ...candidateEditForm, other_contact: event.target.value })} disabled={candidateEditSaving} />
              </label>
              <CandidateSelectField label="Home language" value={candidateEditForm.home_language} options={candidateProfileOptions.languages} onChange={(home_language) => setCandidateEditForm({ ...candidateEditForm, home_language })} disabled={candidateEditSaving || shiftOptionsLoading} />
              <CandidateSelectField label="Country of origin" value={candidateEditForm.country_of_origin} options={candidateProfileOptions.countries} onChange={(country_of_origin) => setCandidateEditForm({ ...candidateEditForm, country_of_origin })} disabled={candidateEditSaving || shiftOptionsLoading} />
              <CandidateSelectField label="Nationality" value={candidateEditForm.nationality} options={candidateProfileOptions.countries} onChange={(nationality) => setCandidateEditForm({ ...candidateEditForm, nationality })} disabled={candidateEditSaving || shiftOptionsLoading} />
              <CandidateSelectField label="Division" value={candidateEditForm.division} options={candidateProfileOptions.divisions} onChange={(division) => setCandidateEditForm({ ...candidateEditForm, division })} disabled={candidateEditSaving || shiftOptionsLoading} />
              <CandidateSelectField label="Consultant" value={candidateEditForm.assigned_consultant} options={candidateProfileOptions.consultants} onChange={(assigned_consultant) => setCandidateEditForm({ ...candidateEditForm, assigned_consultant })} disabled={candidateEditSaving || shiftOptionsLoading} />
              <label className="candidate-active-toggle">
                <input type="checkbox" checked={candidateEditForm.is_locum} onChange={(event) => setCandidateEditForm({ ...candidateEditForm, is_locum: event.target.checked })} disabled={candidateEditSaving} />
                <span>Locum</span>
              </label>
              <label className="candidate-active-toggle">
                <input type="checkbox" checked={candidateEditForm.is_permanent} onChange={(event) => setCandidateEditForm({ ...candidateEditForm, is_permanent: event.target.checked })} disabled={candidateEditSaving} />
                <span>Permanent</span>
              </label>
              <label>
                <span>Region</span>
                <select
                  value={candidateEditForm.home_region}
                  onChange={(event) => {
                    const home_region = event.target.value
                    const configuredAreas = candidateLocations.find(
                      (location) => location.region === home_region,
                    )?.areas ?? []
                    setCandidateEditForm({
                      ...candidateEditForm,
                      home_region,
                      home_area: configuredAreas.includes(candidateEditForm.home_area)
                        ? candidateEditForm.home_area
                        : '',
                    })
                  }}
                  disabled={candidateEditSaving || shiftOptionsLoading}
                >
                  <option value="">Select region</option>
                  {candidateRegionOptions(candidateLocations, candidateEditForm.home_region).map((region) => (
                    <option key={region} value={region}>{region}</option>
                  ))}
                </select>
              </label>
              <label>
                <span>Area</span>
                <select
                  value={candidateEditForm.home_area}
                  onChange={(event) => setCandidateEditForm({ ...candidateEditForm, home_area: event.target.value })}
                  disabled={candidateEditSaving || shiftOptionsLoading || !candidateEditForm.home_region}
                >
                  <option value="">Select area</option>
                  {candidateAreaOptions(
                    candidateLocations,
                    candidateEditForm.home_region,
                    candidateEditForm.home_area,
                  ).map((area) => (
                    <option key={area} value={area}>{area}</option>
                  ))}
                </select>
              </label>
              <label>
                <span>Postal code</span>
                <input
                  value={candidateEditForm.postal_code}
                  onChange={(event) => setCandidateEditForm({ ...candidateEditForm, postal_code: event.target.value })}
                  disabled={candidateEditSaving}
                />
              </label>
              <label className="full-width">
                <span>Physical address</span>
                <textarea value={candidateEditForm.physical_address} onChange={(event) => setCandidateEditForm({ ...candidateEditForm, physical_address: event.target.value })} disabled={candidateEditSaving} rows={3} />
              </label>
              <label className="full-width">
                <span>Note</span>
                <textarea value={candidateEditForm.note} onChange={(event) => setCandidateEditForm({ ...candidateEditForm, note: event.target.value })} disabled={candidateEditSaving} rows={3} />
              </label>
              <fieldset className="candidate-role-fieldset full-width" disabled={candidateEditSaving || shiftOptionsLoading}>
                <legend>Candidate roles</legend>
                <p>Select every role this Candidate can be matched against.</p>
                <div className="candidate-role-list">
                  {shiftOptions.professions.map((profession) => (
                    <label key={profession.id}>
                      <input
                        type="checkbox"
                        checked={candidateEditForm.profession_ids.includes(profession.id)}
                        onChange={(event) => {
                          const profession_ids = event.target.checked
                            ? [...candidateEditForm.profession_ids, profession.id]
                            : candidateEditForm.profession_ids.filter((id) => id !== profession.id)
                          const allowedLegacyIds = new Set(
                            shiftOptions.professions
                              .filter((option) => profession_ids.includes(option.id))
                              .map((option) => option.legacy_mysql_id)
                              .filter((legacyId): legacyId is number => legacyId != null),
                          )
                          setCandidateEditForm({
                            ...candidateEditForm,
                            profession_ids,
                            qualification_types: candidateEditForm.qualification_types.filter((label) => {
                              const option = candidateProfileOptions.qualification_types.find(
                                (candidateOption) => candidateOption.label === label,
                              )
                              return !option || allowedLegacyIds.has(Number(option.id))
                            }),
                          })
                        }}
                      />
                      <span>{profession.name}</span>
                    </label>
                  ))}
                </div>
              </fieldset>
              </div>}
              {candidateEditTab === 'general2' && <div
                id="candidate-general2-panel"
                className="candidate-profile-grid full-width"
                role="tabpanel"
                aria-labelledby="candidate-general2-tab"
              >
                <CandidateSelectField
                  label="Employment Equity"
                  value={candidateEditForm.employment_equity}
                  options={candidateProfileOptions.employment_equity}
                  onChange={(employment_equity) => setCandidateEditForm({ ...candidateEditForm, employment_equity })}
                  disabled={candidateEditSaving || shiftOptionsLoading}
                  hint="Self-identified; never derived from an identity number."
                />
                <label>
                  <span>Sex</span>
                  <select aria-label="Sex" value={candidateEditForm.sex} onChange={(event) => setCandidateEditForm({ ...candidateEditForm, sex: event.target.value })} disabled={candidateEditSaving || candidateEditForm.is_sa_id}>
                    <option value="">Select sex</option>
                    {candidateProfileOptions.sexes.map((option) => <option key={option.id} value={String(option.id)}>{option.label}</option>)}
                  </select>
                  {candidateEditProfile?.sex_source === 'sa_id' && <small className="field-hint">Derived from validated South African ID</small>}
                </label>
                <label>
                  <span>Citizenship status</span>
                  <input
                    aria-label="Citizenship status"
                    value={candidateEditForm.citizenship_status
                      ? candidateEditForm.citizenship_status.replaceAll('_', ' ')
                      : 'Not derived'}
                    readOnly
                  />
                  <small className="field-hint">Validated from a South African ID; it does not overwrite nationality.</small>
                </label>
                <label className="candidate-active-toggle">
                  <input type="checkbox" checked={candidateEditForm.is_disabled} onChange={(event) => setCandidateEditForm({ ...candidateEditForm, is_disabled: event.target.checked })} disabled={candidateEditSaving} />
                  <span>Disabled</span>
                </label>
                <CandidateSelectField
                  label="Fingerprint status"
                  value={candidateEditForm.fingerprint_status}
                  options={candidateProfileOptions.fingerprint_statuses}
                  onChange={(fingerprint_status) => setCandidateEditForm({ ...candidateEditForm, fingerprint_status })}
                  disabled={candidateEditSaving || !candidateEditProfile?.can_set_compliance}
                  hint={!candidateEditProfile?.can_set_compliance ? 'Managed by the compliance team.' : ''}
                />
                <CandidateSelectField
                  label="Criminal check"
                  value={candidateEditForm.criminal_check}
                  options={candidateProfileOptions.criminal_checks}
                  onChange={(criminal_check) => setCandidateEditForm({ ...candidateEditForm, criminal_check })}
                  disabled={candidateEditSaving || !candidateEditProfile?.can_set_compliance}
                  hint={!candidateEditProfile?.can_set_compliance ? 'Managed by the compliance team.' : ''}
                />
                <CandidateSelectField label="Driver's licence" value={candidateEditForm.drivers_license} options={candidateProfileOptions.drivers_licenses} onChange={(drivers_license) => setCandidateEditForm({ ...candidateEditForm, drivers_license })} disabled={candidateEditSaving} />
                <label className="candidate-active-toggle">
                  <input type="checkbox" checked={candidateEditForm.owns_car} onChange={(event) => setCandidateEditForm({ ...candidateEditForm, owns_car: event.target.checked })} disabled={candidateEditSaving} />
                  <span>Own car</span>
                </label>
                <CandidateSelectField label="Qualification" value={candidateEditForm.qualification} options={candidateProfileOptions.qualifications} onChange={(qualification) => setCandidateEditForm({ ...candidateEditForm, qualification })} disabled={candidateEditSaving} />
                <label>
                  <span>Qualification types</span>
                  <select
                    multiple
                    value={candidateEditForm.qualification_types}
                    onChange={(event) => setCandidateEditForm({
                      ...candidateEditForm,
                      qualification_types: Array.from(event.target.selectedOptions, (option) => option.value),
                    })}
                    disabled={candidateEditSaving}
                  >
                    {candidateQualificationTypeOptions(
                      candidateProfileOptions.qualification_types,
                      candidateEditForm.qualification_types,
                      shiftOptions.professions,
                      candidateEditForm.profession_ids,
                    ).map((option) => <option key={option.id} value={option.label}>{option.label}</option>)}
                  </select>
                </label>
                <CandidateSelectField label="Education level" value={candidateEditForm.education_level} options={candidateProfileOptions.education_levels} onChange={(education_level) => setCandidateEditForm({ ...candidateEditForm, education_level })} disabled={candidateEditSaving} />
                <CandidateSelectField label="Source" value={candidateEditForm.source} options={candidateProfileOptions.sources} onChange={(source) => setCandidateEditForm({ ...candidateEditForm, source })} disabled={candidateEditSaving} />
                <CandidateSelectField label="Marital status" value={candidateEditForm.marital_status} options={candidateProfileOptions.marital_statuses} onChange={(marital_status) => setCandidateEditForm({ ...candidateEditForm, marital_status })} disabled={candidateEditSaving} />
                <label className="full-width">
                  <span>Other languages</span>
                  <select
                    aria-label="Other languages"
                    multiple
                    value={candidateEditForm.other_languages}
                    onChange={(event) => setCandidateEditForm({
                      ...candidateEditForm,
                      other_languages: Array.from(event.target.selectedOptions, (option) => option.value),
                    })}
                    disabled={candidateEditSaving}
                  >
                    {candidateProfileOptionsWithHistorical(
                      candidateProfileOptions.languages,
                      candidateEditForm.other_languages,
                    ).map((option) => <option key={option.id} value={option.label}>{option.label}</option>)}
                  </select>
                </label>
              </div>}
              {candidateEditError && <p className="form-error full-width" role="alert">{candidateEditError}</p>}
              <div className="form-actions full-width">
                <button
                  type="button"
                  className="secondary-button"
                  disabled={candidateEditSaving}
                  onClick={closeCandidateEditor}
                >Cancel</button>
                <button
                  className="primary-button"
                  disabled={candidateEditSaving || shiftOptionsLoading || !candidateEditProfile || candidateEditForm.profession_ids.length === 0}
                >{candidateEditSaving ? 'Saving…' : 'Save candidate changes'}</button>
              </div>
            </form>
          </section>
        </div>
      )}

      {candidateFormOpen && (
        <div className="modal-backdrop" role="presentation">
          <section ref={candidateFormDialogRef} className="shift-modal candidate-modal" role="dialog" aria-modal="true" aria-labelledby="new-candidate-title" tabIndex={-1}>
            <div className="drawer-header">
              <div>
                <p className="eyebrow">Candidate directory</p>
                <h2 id="new-candidate-title">Add candidate</h2>
                <p>New candidates remain pending until their compliance is cleared.</p>
              </div>
              <button
                className="close-button"
                data-dialog-close
                aria-label="Close candidate form"
                disabled={candidateSaving}
                onClick={() => {
                  setCandidateFormOpen(false)
                  setCandidateFormError('')
                }}
              >×</button>
            </div>
            <form className="shift-form" onSubmit={createCandidate}>
              <label>
                <span>First name</span>
                <input
                  data-dialog-initial-focus
                  value={candidateForm.first_name}
                  onChange={(event) => setCandidateForm({ ...candidateForm, first_name: event.target.value })}
                  disabled={candidateSaving}
                  required
                />
              </label>
              <label>
                <span>Last name</span>
                <input
                  value={candidateForm.last_name}
                  onChange={(event) => setCandidateForm({ ...candidateForm, last_name: event.target.value })}
                  disabled={candidateSaving}
                  required
                />
              </label>
              <label>
                <span>Region</span>
                <select
                  value={candidateForm.home_region}
                  onChange={(event) => setCandidateForm({
                    ...candidateForm,
                    home_region: event.target.value,
                    home_area: '',
                  })}
                  disabled={candidateSaving || shiftOptionsLoading}
                >
                  <option value="">Select region</option>
                  {candidateRegionOptions(candidateLocations, candidateForm.home_region).map((region) => (
                    <option key={region} value={region}>{region}</option>
                  ))}
                </select>
              </label>
              <label>
                <span>Area</span>
                <select
                  value={candidateForm.home_area}
                  onChange={(event) => setCandidateForm({ ...candidateForm, home_area: event.target.value })}
                  disabled={candidateSaving || shiftOptionsLoading || !candidateForm.home_region}
                >
                  <option value="">Select area</option>
                  {candidateAreaOptions(
                    candidateLocations,
                    candidateForm.home_region,
                    candidateForm.home_area,
                  ).map((area) => (
                    <option key={area} value={area}>{area}</option>
                  ))}
                </select>
              </label>
              <label className="full-width">
                <span>Candidate role</span>
                <select
                  value={candidateForm.profession}
                  onChange={(event) => setCandidateForm({ ...candidateForm, profession: event.target.value })}
                  disabled={candidateSaving || shiftOptionsLoading}
                  required
                >
                  <option value="">{shiftOptionsLoading ? 'Loading roles…' : 'Select role'}</option>
                  {shiftOptions.professions.map((profession) => (
                    <option key={profession.id} value={profession.id}>{profession.name}</option>
                  ))}
                </select>
              </label>
              {candidateFormError && <p className="form-error full-width" role="alert">{candidateFormError}</p>}
              <div className="form-actions full-width">
                <button
                  type="button"
                  className="secondary-button"
                  disabled={candidateSaving}
                  onClick={() => setCandidateFormOpen(false)}
                >Cancel</button>
                <button className="primary-button" disabled={candidateSaving || shiftOptionsLoading || shiftOptions.professions.length === 0}>
                  {candidateSaving ? 'Saving…' : 'Save candidate'}
                </button>
              </div>
            </form>
          </section>
        </div>
      )}

      {shiftFormOpen && (
        <div className="modal-backdrop" role="presentation">
          <section ref={vacancyDialogRef} className="shift-modal" role="dialog" aria-modal="true" aria-labelledby="new-vacancy-title" tabIndex={-1}>
            <div className="drawer-header">
              <div>
                <p className="eyebrow">Schedule</p>
                <h2
                  id="new-vacancy-title"
                  tabIndex={bookNowFacility ? -1 : undefined}
                  data-dialog-initial-focus={bookNowFacility ? true : undefined}
                >{bookNowFacility ? 'Book now' : 'Create vacancy'}</h2>
                <p>{bookNowFacility
                  ? `${bookNowFacility.client_name} · ${bookNowFacility.name}`
                  : 'Add all required shifts now, then book the best eligible locums.'}</p>
              </div>
              <button
                className="close-button"
                data-dialog-close
                aria-label="Close new vacancy form"
                disabled={shiftSaving}
                onClick={closeShiftForm}
              >×</button>
            </div>
            {shiftOptionsLoading ? (
              <p className="state-message">Loading facilities and roles…</p>
            ) : (
              <form className="shift-form" onSubmit={createShift}>
                {!bookNowFacility && <>
                  <label className="full-width">
                    <span>Reference</span>
                    <input
                      data-dialog-initial-focus
                      value={shiftForm.reference}
                      onChange={(event) => {
                        setShiftForm({ ...shiftForm, reference: event.target.value })
                        setShiftFormError('')
                      }}
                      placeholder="e.g. Weekend cover"
                      disabled={shiftSaving}
                      required
                    />
                  </label>
                  <label className="full-width">
                    <span>Search facilities</span>
                    <input
                      type="search"
                      value={facilitySearch}
                      onChange={(event) => setFacilitySearch(event.target.value)}
                      placeholder="Type a facility or client name"
                      disabled={shiftSaving}
                    />
                  </label>
                </>}
                <label>
                  <span>Facility</span>
                  <select
                    value={shiftForm.site}
                    onChange={(event) => {
                      setShiftForm({
                        ...shiftForm,
                        site: event.target.value,
                        profession: '',
                        pay_rate: '',
                      })
                      setSiteRoleOptions([])
                      setShiftFormError('')
                    }}
                    disabled={shiftSaving || Boolean(bookNowFacility)}
                    required
                  >
                    <option value="">Select facility</option>
                    {filteredFacilityOptions.map((site) => (
                      <option key={site.id} value={site.id}>{site.client_name} · {site.name}</option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>Role</span>
                  <select
                    value={shiftForm.profession}
                    onChange={(event) => {
                      const role = siteRoleOptions.find(
                        (option) => option.id === Number(event.target.value),
                      )
                      setShiftForm({
                        ...shiftForm,
                        profession: event.target.value,
                        pay_rate: role?.pay_rate ?? '',
                      })
                      if (!bookNowFacility || !role) {
                        bookNowCandidateRequestId.current += 1
                        setBookNowCandidates([])
                        setBookNowCandidateId('')
                        setBookNowCandidateError('')
                      }
                      setShiftFormError('')
                    }}
                    disabled={shiftSaving || !shiftForm.site || roleOptionsLoading}
                    required
                  >
                    <option value="">
                      {!shiftForm.site
                        ? 'Select facility first'
                        : roleOptionsLoading
                          ? 'Loading linked roles…'
                          : siteRoleOptions.length === 0
                            ? 'No linked roles'
                            : 'Select role'}
                    </option>
                    {siteRoleOptions.map((profession) => (
                      <option key={profession.id} value={profession.id}>{profession.name}</option>
                    ))}
                  </select>
                </label>
                {roleOptionsError && (
                  <div className="state-action compact full-width" role="alert">
                    <p className="state-message error">{roleOptionsError}</p>
                    <button
                      type="button"
                      className="secondary-button"
                      onClick={() => setRoleOptionsReload((current) => current + 1)}
                    >Retry roles</button>
                  </div>
                )}
                <div className="vacancy-shifts full-width">
                  <div className="vacancy-shifts-heading">
                    <strong>Shifts</strong>
                    {!bookNowFacility && <button type="button" className="secondary-button" disabled={shiftSaving} onClick={addShiftItem}>
                      Add another shift
                    </button>}
                  </div>
                  {shiftForm.shift_items.map((item, index) => (
                    <div className="shift-time-row" key={index}>
                      <label>
                        <span>{`Start ${index + 1}`}</span>
                        <input
                          type="datetime-local"
                          step={bookingTimeStepSeconds}
                          value={item.starts_at}
                          onChange={(event) => updateShiftItem(index, 'starts_at', event.target.value)}
                          disabled={shiftSaving}
                          required
                        />
                      </label>
                      <label>
                        <span>{`End ${index + 1}`}</span>
                        <input
                          type="datetime-local"
                          step={bookingTimeStepSeconds}
                          value={item.ends_at}
                          onChange={(event) => updateShiftItem(index, 'ends_at', event.target.value)}
                          disabled={shiftSaving}
                          required
                        />
                      </label>
                      {shiftForm.shift_items.length > 1 && (
                        <button
                          type="button"
                          className="remove-shift-button"
                          disabled={shiftSaving}
                          onClick={() => removeShiftItem(index)}
                        >
                          Remove shift
                        </button>
                      )}
                    </div>
                  ))}
                </div>
                {bookNowFacility ? (
                  <label className="full-width">
                    <span>Candidate</span>
                    <select
                      value={bookNowCandidateId}
                      onChange={(event) => {
                        setBookNowCandidateId(event.target.value)
                        setShiftFormError('')
                      }}
                      disabled={shiftSaving || bookNowCandidateLoading || !shiftForm.profession}
                      required
                    >
                      <option value="">{!shiftForm.profession
                        ? 'Select role first'
                        : !shiftForm.shift_items[0].starts_at || !shiftForm.shift_items[0].ends_at
                          ? 'Select start and end first'
                          : bookNowCandidateLoading
                            ? 'Loading matching candidates…'
                            : bookNowCandidateError
                              ? 'Candidates unavailable'
                              : bookNowCandidates.length === 0
                                ? 'No compliance-cleared matching candidates'
                                : 'Select candidate'}</option>
                      {bookNowCandidates.map((candidate) => (
                        <option key={candidate.id} value={candidate.id}>
                          {candidate.full_name}{candidate.worked_at_facility
                            ? ` · worked here (${candidate.facility_shift_count})`
                            : candidate.proximity_label
                              ? ` · ${candidate.proximity_label}`
                              : ''}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : <>
                  {canViewCandidatePayRates && canOverrideApprovedRates && (
                    <label>
                      <span>Pay rate</span>
                      <input
                        type="number"
                        min="0"
                        step="0.01"
                        value={shiftForm.pay_rate}
                        onChange={(event) => {
                          setShiftForm({ ...shiftForm, pay_rate: event.target.value })
                          setShiftFormError('')
                        }}
                        disabled={shiftSaving}
                        required
                      />
                    </label>
                  )}
                  {canViewCandidatePayRates && !canOverrideApprovedRates && shiftForm.pay_rate && (
                    <p className="state-message">Approved pay rate: R{shiftForm.pay_rate}/hr</p>
                  )}

                  <label className="full-width">
                    <span>Notes</span>
                    <textarea
                      value={shiftForm.notes}
                      onChange={(event) => {
                        setShiftForm({ ...shiftForm, notes: event.target.value })
                        setShiftFormError('')
                      }}
                      disabled={shiftSaving}
                      rows={3}
                    />
                  </label>
                </>}
                {bookNowCandidateError && (
                  <div className="state-action compact full-width" role="alert">
                    <p className="state-message error">{bookNowCandidateError}</p>
                    <button
                      type="button"
                      className="secondary-button"
                      onClick={() => setBookNowCandidateReload((current) => current + 1)}
                    >Retry candidates</button>
                  </div>
                )}
                {shiftFormError && <p className="form-error full-width" role="alert">{shiftFormError}</p>}
                <div className="form-actions full-width">
                  <button type="button" className="secondary-button" disabled={shiftSaving} onClick={closeShiftForm}>Cancel</button>
                  <button className="primary-button" disabled={shiftSaving || roleOptionsLoading || shiftOptions.sites.length === 0 || siteRoleOptions.length === 0 || (Boolean(bookNowFacility) && !bookNowCandidateId)}>
                    {shiftSaving
                      ? 'Creating…'
                      : bookNowFacility
                        ? 'Create vacancy and book'
                        : 'Create vacancy'}
                  </button>
                </div>
              </form>
            )}
          </section>
        </div>
      )}

      {(batchCandidate || batchFacility) && (
        <div className="drawer-backdrop" role="presentation">
          <section
            ref={batchDialogRef}
            className="candidate-drawer"
            role="dialog"
            aria-modal="true"
            aria-label={batchCandidate
              ? `Book multiple shifts for ${batchCandidate.full_name}`
              : `Create multiple bookings for ${batchFacility?.client_name} ${batchFacility?.name}`}
            tabIndex={-1}
          >
            <div className="drawer-header">
              <div>
                <p className="eyebrow">Multiple booking</p>
                <h2>{batchCandidate ? 'Book multiple shifts' : 'Create multiple bookings'}</h2>
                <p>{batchCandidate
                  ? `${batchCandidate.full_name} · ${batchCandidate.profession_names.join(', ')}`
                  : `${batchFacility?.client_name} · ${batchFacility?.name}`}</p>
              </div>
              <button
                className="close-button"
                data-dialog-close
                aria-label="Close multiple booking"
                disabled={batchSaving}
                onClick={closeBatchDialog}
              >×</button>
            </div>
            {batchLoading && <p className="state-message">{batchCandidate
              ? 'Loading compatible shifts…'
              : 'Loading eligible candidates…'}</p>}
            {!batchLoading && !batchCreatingNew && batchShifts.length === 0 && !batchError && (
              <div className="state-action">
                <p className="state-message">No compatible open shifts are available.</p>
                {batchCandidate && (
                  <button className="primary-button" onClick={() => void openCandidateShiftCreation()}>
                    Create new shifts
                  </button>
                )}
              </div>
            )}
            {batchError && (
              <div className="state-action" role="alert">
                <p className="state-message error">{batchError}</p>
                {batchCreatingNew && batchCandidate && batchCreationFailure && (
                  <button
                    className="secondary-button"
                    onClick={() => {
                      if (batchCreationFailure === 'roles') {
                        void selectCandidateShiftFacility(batchCreationForm.site)
                      } else {
                        void openCandidateShiftCreation()
                      }
                    }}
                  >{batchCreationFailure === 'roles' ? 'Retry Facility roles' : 'Retry Facilities'}</button>
                )}
                {!batchCreatingNew && (batchFacility || batchShifts.length === 0) && (
                  <button
                    className="secondary-button"
                    onClick={() => {
                      if (batchCandidate) void openCandidateBatch(batchCandidate)
                      else if (batchFacility) void openFacilityBatch(batchFacility)
                    }}
                  >Retry matching</button>
                )}
              </div>
            )}
            {batchCreatingNew && batchCandidate && (
              <form className="batch-booking-form" onSubmit={submitCandidateShiftCreation}>
                <h3 tabIndex={-1} data-dialog-initial-focus>Create and book new shifts</h3>
                {batchCreationLoading && <p className="state-message">Loading booking options…</p>}
                <label>
                  <span>Facility</span>
                  <select
                    value={batchCreationForm.site}
                    disabled={batchSaving || batchCreationLoading}
                    required
                    onChange={(event) => void selectCandidateShiftFacility(event.target.value)}
                  >
                    <option value="">Select Facility</option>
                    {shiftOptions.sites.map((site) => (
                      <option value={site.id} key={site.id}>{site.client_name} · {site.name}</option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>Role</span>
                  <select
                    value={batchCreationForm.profession}
                    disabled={batchSaving || batchCreationLoading || !batchCreationForm.site}
                    required
                    onChange={(event) => setBatchCreationForm((current) => ({
                      ...current, profession: event.target.value,
                    }))}
                  >
                    <option value="">{batchCreationForm.site && !batchCreationLoading && batchCreationRoles.length === 0
                      ? 'No matching configured roles'
                      : 'Select role'}</option>
                    {batchCreationRoles.map((role) => (
                      <option value={role.id} key={role.id}>{role.name}</option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>Reference (optional)</span>
                  <input
                    value={batchCreationForm.reference}
                    disabled={batchSaving}
                    onChange={(event) => setBatchCreationForm((current) => ({
                      ...current, reference: event.target.value,
                    }))}
                  />
                </label>
                <div className="batch-shift-list">
                  {batchCreationForm.shift_items.map((shiftItem, index) => (
                    <article className="batch-shift-option" key={index}>
                      <label>
                        <span>{`Shift ${index + 1} start`}</span>
                        <input
                          type="datetime-local"
                          step={bookingTimeStepSeconds}
                          required
                          value={shiftItem.starts_at}
                          disabled={batchSaving}
                          onChange={(event) => setBatchCreationForm((current) => ({
                            ...current,
                            shift_items: current.shift_items.map((item, itemIndex) => itemIndex === index
                              ? {
                                  ...item,
                                  starts_at: event.target.value,
                                  ends_at: addHoursToLocalDateTime(
                                    event.target.value,
                                    DEFAULT_SHIFT_DURATION_HOURS,
                                  ),
                                }
                              : item),
                          }))}
                        />
                      </label>
                      <label>
                        <span>{`Shift ${index + 1} end`}</span>
                        <input
                          type="datetime-local"
                          step={bookingTimeStepSeconds}
                          required
                          value={shiftItem.ends_at}
                          disabled={batchSaving}
                          onChange={(event) => setBatchCreationForm((current) => ({
                            ...current,
                            shift_items: current.shift_items.map((item, itemIndex) => itemIndex === index
                              ? { ...item, ends_at: event.target.value }
                              : item),
                          }))}
                        />
                      </label>
                      {batchCreationForm.shift_items.length > 1 && (
                        <button
                          type="button"
                          className="secondary-button"
                          disabled={batchSaving}
                          onClick={() => setBatchCreationForm((current) => ({
                            ...current,
                            shift_items: current.shift_items.filter((_, itemIndex) => itemIndex !== index),
                          }))}
                        >{`Remove Shift ${index + 1}`}</button>
                      )}
                    </article>
                  ))}
                </div>
                <button
                  type="button"
                  className="secondary-button"
                  disabled={batchSaving || batchCreationForm.shift_items.length >= 100}
                  onClick={() => setBatchCreationForm((current) => ({
                    ...current,
                    shift_items: [...current.shift_items, { starts_at: '', ends_at: '' }],
                  }))}
                >Add another shift</button>
                <div className="form-actions">
                  <button type="button" className="secondary-button" disabled={batchSaving} onClick={() => {
                    setBatchCreatingNew(false)
                    setBatchError('')
                  }}>Back</button>
                  <button
                    className="primary-button"
                    disabled={batchSaving || batchCreationLoading || !batchCreationForm.site || !batchCreationForm.profession}
                  >{batchSaving
                      ? 'Booking…'
                      : `Create and book ${batchCreationForm.shift_items.length} ${batchCreationForm.shift_items.length === 1 ? 'shift' : 'shifts'}`}</button>
                </div>
              </form>
            )}
            {!batchCreatingNew && !batchLoading && batchShifts.length > 0 && (
              <form className="batch-booking-form" onSubmit={(event) => {
                event.preventDefault()
                if (batchCandidate) void submitCandidateBatch()
                else void submitFacilityBatch()
              }}>
                <div className="batch-shift-list">
                  {batchShifts.map((shift, index) => batchCandidate ? (
                    <label className="batch-shift-option" key={shift.id}>
                      <input
                        data-dialog-initial-focus={index === 0 ? true : undefined}
                        type="checkbox"
                        checked={batchAssignments[shift.id] === batchCandidate.id}
                        disabled={batchSaving}
                        onChange={() => toggleCandidateBatchShift(shift.id)}
                      />
                      <span>
                        <strong>{shift.client_name} · {shift.site_name}</strong>
                        <small>{shift.profession_name} · {formatDate(shift.starts_at)} – {formatDate(shift.ends_at)}</small>
                      </span>
                    </label>
                  ) : (
                    <article className="batch-shift-option facility-assignment" key={shift.id}>
                      <span>
                        <strong>{shift.profession_name}</strong>
                        <small>{formatDate(shift.starts_at)} – {formatDate(shift.ends_at)}</small>
                      </span>
                      <label>
                        <span>{`Eligible candidate for Shift ${shift.id}, ${shift.profession_name}, ${formatDate(shift.starts_at)} to ${formatDate(shift.ends_at)}`}</span>
                        <select
                          data-dialog-initial-focus={index === 0 ? true : undefined}
                          value={batchAssignments[shift.id] || ''}
                          disabled={batchSaving || (batchCandidatesByShift[shift.id]?.length || 0) === 0}
                          onChange={(event) => setFacilityBatchCandidate(shift.id, event.target.value)}
                        >
                          <option value="">{(batchCandidatesByShift[shift.id]?.length || 0) === 0
                            ? 'No eligible candidates'
                            : 'Select candidate'}</option>
                          {(batchCandidatesByShift[shift.id] || []).map((candidate) => (
                            <option value={candidate.id} key={candidate.id}>{candidate.full_name}</option>
                          ))}
                        </select>
                      </label>
                    </article>
                  ))}
                </div>
                <div className="form-actions">
                  <button type="button" className="secondary-button" disabled={batchSaving} onClick={closeBatchDialog}>Cancel</button>
                  <button className="primary-button" disabled={batchSaving || Object.keys(batchAssignments).length === 0}>
                    {batchSaving
                      ? 'Booking…'
                      : batchCandidate
                        ? `Book ${Object.keys(batchAssignments).length} ${Object.keys(batchAssignments).length === 1 ? 'shift' : 'shifts'}`
                        : `Book ${Object.keys(batchAssignments).length} ${Object.keys(batchAssignments).length === 1 ? 'assignment' : 'assignments'}`}
                  </button>
                </div>
              </form>
            )}
          </section>
        </div>
      )}

      {selectedShift && (
        <div className="drawer-backdrop" role="presentation">
          <section
            ref={candidateFinderDialogRef}
            className="candidate-drawer"
            role="dialog"
            aria-modal="true"
            aria-label={selectedShift.confirmed_booking ? 'Booking details' : 'Eligible candidates'}
            tabIndex={-1}
          >
            <div className="drawer-header">
              <div>
                <p className="eyebrow">
                  {selectedShift.confirmed_booking ? 'Booking details' : 'Candidate matching'}
                </p>
                <h2>{selectedShift.confirmed_booking ? 'Filled booking' : 'Eligible candidates'}</h2>
                <p>{selectedShift.client_name} · {selectedShift.profession_name}</p>
              </div>
              <button
                className="close-button"
                data-dialog-close
                aria-label="Close candidate finder"
                disabled={confirmingCandidateId !== null || bookingSmsSending}
                onClick={closeCandidateFinder}
              >×</button>
            </div>
            {selectedShift.confirmed_booking ? (
              <>
              <article className="candidate-card filled-booking-card">
                <div className="candidate-initials">
                  {selectedShift.confirmed_booking.candidate_name
                    .split(' ')
                    .map((part) => part[0])
                    .join('')
                    .slice(0, 2)}
                </div>
                <div className="candidate-profile">
                  <div className="candidate-name-row">
                    <strong>{selectedShift.confirmed_booking.candidate_name}</strong>
                    <span className="status-pill booked">Confirmed</span>
                  </div>
                  <p>Confirmed candidate</p>
                  <div className="match-reasons">
                    <span><i aria-hidden="true">✓</i> <span>{selectedShift.profession_name}</span></span>
                    <span><i aria-hidden="true">✓</i> <span>{formatDate(selectedShift.starts_at)}</span></span>
                  </div>
                </div>
              </article>
              {canSendBookingSms && (
                <section className="booking-sms-panel" aria-labelledby="booking-sms-heading">
                  <h3 id="booking-sms-heading">Candidate SMS</h3>
                  {bookingSmsLoading && <p className="state-message">Loading SMS preview…</p>}
                  {bookingSmsError && (
                    <div className="state-action" role="alert">
                      <p className="state-message error">{bookingSmsError}</p>
                      <button
                        type="button"
                        className="secondary-button"
                        aria-label="Retry SMS preview"
                        onClick={() => setBookingSmsReload((value) => value + 1)}
                      >Retry</button>
                    </div>
                  )}
                  {!bookingSmsLoading && bookingSms && (
                    <>
                      <p>To {bookingSms.destination}</p>
                      <label>
                        <span>SMS message</span>
                        <textarea
                          value={bookingSms.body}
                          maxLength={459}
                          rows={5}
                          disabled={bookingSms.status !== 'not_queued' || bookingSmsSending}
                          onChange={(event) => setBookingSms({ ...bookingSms, body: event.target.value })}
                        />
                      </label>
                      <small>{bookingSms.body.length}/459 characters</small>
                      {bookingSms.status === 'not_queued' ? (
                        <button
                          type="button"
                          className="primary-button"
                          disabled={bookingSmsSending || !bookingSms.body.trim()}
                          onClick={() => void queueSelectedBookingSms()}
                        >
                          {bookingSmsSending ? 'Queueing…' : 'Queue SMS'}
                        </button>
                      ) : (
                        <p className="state-message" role="status">
                          {bookingSms.status === 'queued' && 'SMS queued'}
                          {bookingSms.status === 'processing' && 'SMS processing'}
                          {bookingSms.status === 'accepted' && 'SMS accepted by provider'}
                          {bookingSms.status === 'failed' && 'SMS send failed'}
                        </p>
                      )}
                    </>
                  )}
                </section>
              )}
              </>
            ) : (
              <>
            {!candidateLoading && !candidateError && candidates.length > 0 && (
              <label className="candidate-search">
                <span>{candidateSource === 'eligible'
                  ? 'Search eligible candidates'
                  : 'Search full candidate directory'}</span>
                <input
                  data-dialog-initial-focus
                  type="search"
                  value={candidateSearch}
                  onChange={(event) => setCandidateSearch(event.target.value)}
                  placeholder="Type a candidate name or area"
                />
              </label>
            )}
            {candidateLoading && <p className="state-message">{
              candidateSource === 'eligible'
                ? 'Finding eligible candidates…'
                : 'Loading full candidate directory…'
            }</p>}
            {!candidateLoading && candidateError && (
              <div className="state-action" role="alert">
                <p className="state-message error">{candidateError}.</p>
                <button
                  className="secondary-button"
                  aria-label={candidateSource === 'eligible' ? 'Retry eligible candidates' : 'Retry candidate directory'}
                  onClick={() => {
                    if (candidateSource === 'eligible' && selectedShift) void openCandidateFinder(selectedShift)
                    else void loadFullCandidateDirectory()
                  }}
                >Retry</button>
              </div>
            )}
            {!candidateLoading && !candidateError && candidates.length === 0 && (
              <p className="state-message">{candidateSource === 'eligible'
                ? 'No compliance-cleared candidates match this shift.'
                : 'No candidates match the full-directory search.'}</p>
            )}
            {!candidateLoading && !candidateError && candidates.length > 0 && displayedCandidates.length === 0 && (
              <p className="state-message">No eligible candidate matches that search.</p>
            )}
            {!candidateLoading && !candidateError && candidateSource === 'eligible' && (
              <div className="candidate-directory-fallback">
                <p>Can’t find the candidate? Search all active candidate records. Final eligibility is still checked when you add them.</p>
                <button className="secondary-button" onClick={() => void loadFullCandidateDirectory()}>
                  Search full candidate directory
                </button>
              </div>
            )}
            {candidateActionError && (
              <p className="state-message error" role="alert">{candidateActionError}</p>
            )}
            <div className="candidate-list">
              {displayedCandidates.map((candidate) => (
                <article className="candidate-card" key={candidate.id}>
                  <div className="candidate-initials">
                    {candidate.full_name.split(' ').map((part) => part[0]).join('').slice(0, 2)}
                  </div>
                  <div className="candidate-profile">
                    <div className="candidate-name-row">
                      <strong>{candidate.full_name}</strong>
                      {candidate.worked_at_facility && (
                        <span className="experience-badge">Previously worked here</span>
                      )}
                      {candidate.directory_result && (
                        <span className="directory-result-badge">Not prevalidated</span>
                      )}
                    </div>
                    <p>
                      {candidate.role_name || selectedShift.profession_name}
                      {candidate.home_area && ` · ${candidate.home_area}`}
                    </p>
                    <div className="match-reasons">
                      {(candidate.directory_result
                        ? [`Compliance: ${candidate.compliance_status}`, 'Eligibility checked when added']
                        : candidate.eligibility_reasons || ['Compliance cleared']).map((reason) => (
                        <span key={reason}>
                          <i aria-hidden="true">{candidate.directory_result ? '!' : '✓'}</i> <span>{reason}</span>
                        </span>
                      ))}
                    </div>
                  </div>
                  <button
                    className="primary-button"
                    aria-label={`Add ${candidate.full_name} to booking`}
                    disabled={confirmingCandidateId !== null || !canManageBookings}
                    onClick={() => confirmBooking(candidate)}
                  >{
                    !canManageBookings
                      ? 'No booking access'
                      : confirmingCandidateId === candidate.id ? 'Adding…' : 'Add to booking'
                  }</button>
                </article>
              ))}
            </div>
              </>
            )}
          </section>
        </div>
      )}
      {notice && <div className="toast" role="status">✓ <span>{notice}</span></div>}
    </div>
  )
}

export default App
