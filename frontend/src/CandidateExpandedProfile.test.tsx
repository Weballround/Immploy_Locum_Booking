import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'

function syntheticId(datePart: string, sequence: string) {
  const firstTwelve = `${datePart}${sequence}08`
  const provisional = `${firstTwelve}0`
  const sum = [...provisional].reduce((total, character, index) => {
    let digit = Number(character)
    if (index % 2 === 1) {
      digit *= 2
      if (digit > 9) digit -= 9
    }
    return total + digit
  }, 0)
  return `${firstTwelve}${(10 - (sum % 10)) % 10}`
}

const candidate = {
  id: 51,
  first_name: 'Example',
  last_name: 'Candidate',
  full_name: 'Example Candidate',
  email: '',
  phone: '',
  home_area: 'Rosebank',
  home_region: 'Gauteng',
  postal_code: '',
  is_active: true,
  compliance_status: 'cleared',
  profession_names: ['Registered Nurse'],
  profession_ids: [9],
}

const profile = {
  ...candidate,
  preferred_name: '', date_of_birth: '', identity_number: '', is_sa_id: false,
  passport_number: '', visa_type: '', visa_start: '', visa_end: '', visa_selected: false,
  country_of_origin: '', nationality: '', home_language: 'English',
  is_locum: true, is_permanent: false, home_phone: '', other_contact: '',
  physical_address: '', note: '', division: 'Nursing', assigned_consultant: '',
  sex: '', sex_source: '', citizenship_status: '', employment_equity: 'Other/Unspecified',
  is_disabled: false, fingerprint_status: 'No Fingerprint',
  criminal_check: 'No Criminal Check', drivers_license: 'None Assigned', owns_car: false,
  qualification: '', qualification_types: ['Historical Type'], education_level: '', source: '',
  marital_status: '', other_languages: ['English', 'Historical Language'], can_set_compliance: false,
}

const option = (id: number, label: string) => ({ id, label })
const profileOptions = {
  countries: [option(1, 'South Africa')], visa_types: [option(1, 'Work Visa')],
  languages: [option(1, 'English'), option(2, 'Afrikaans')],
  divisions: [option(3, 'Nursing')], consultants: [],
  employment_equity: [option(14, 'Other/Unspecified')],
  education_levels: [option(1, 'Degree/Diploma/N5')],
  qualifications: [option(1, 'Nursing')], qualification_types: [option(1, 'General')],
  sources: [option(1, 'Word of Mouth')], marital_statuses: [option(1, 'Single')],
  drivers_licenses: [option(1, 'None Assigned')],
  fingerprint_statuses: [option(1, 'No Fingerprint')],
  criminal_checks: [option(1, 'No Criminal Check')],
  sexes: [{ id: 'female', label: 'Female' }, { id: 'male', label: 'Male' }],
}

describe('expanded Candidate profile', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('links validated ID fields without deriving employment equity', async () => {
    const idNumber = syntheticId('000101', '4000')
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
      if (url === '/api/session/') return Promise.resolve({
        ok: true,
        json: async () => ({ authenticated: true, permissions: { manage_candidates: true } }),
      })
      if (url === '/api/candidates/' && !options?.method) {
        return Promise.resolve({ ok: true, json: async () => [candidate] })
      }
      if (url === '/api/candidates/51/profile/' && !options?.method) {
        return Promise.resolve({ ok: true, json: async () => profile })
      }
      if (url === '/api/candidates/creation-options/') return Promise.resolve({
        ok: true,
        json: async () => ({
          professions: [{ id: 9, name: 'Registered Nurse', legacy_mysql_id: 1 }],
          locations: [{ region: 'Gauteng', areas: ['Rosebank'] }],
          profile: profileOptions,
        }),
      })
      if (url === '/api/candidates/decode-sa-id/' && options?.method === 'POST') {
        return Promise.resolve({ ok: true, json: async () => ({
          date_of_birth: '2000-01-01', sex: 'female', sex_source: 'sa_id',
          citizenship_status: 'citizen',
        }) })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: 'Edit Example Candidate' }))
    const dialog = await screen.findByRole('dialog', { name: 'Edit Example Candidate' })
    await waitFor(() => expect(within(dialog).getByLabelText('Home language')).toHaveValue('English'))

    expect(within(dialog).getByRole('tab', { name: 'General' })).toHaveAttribute('aria-selected', 'true')
    await user.click(within(dialog).getByLabelText('South African ID'))
    await user.type(within(dialog).getByLabelText('ID number'), `${idNumber}9`)
    expect(within(dialog).getByLabelText('ID number')).toHaveValue(idNumber)
    await user.tab()

    await waitFor(() => expect(within(dialog).getByLabelText('Date of birth')).toHaveValue('2000-01-01'))
    expect(within(dialog).getByText('Derived from validated South African ID')).toBeInTheDocument()

    within(dialog).getByRole('tab', { name: 'General' }).focus()
    await user.keyboard('{ArrowRight}')
    expect(within(dialog).getByRole('tab', { name: 'General 2' })).toHaveFocus()
    expect(within(dialog).getByRole('tab', { name: 'General 2' })).toHaveAttribute('aria-selected', 'true')
    expect(within(dialog).getByRole('tab', { name: 'General' })).toHaveAttribute('tabindex', '-1')
    await user.keyboard('{ArrowLeft}')
    expect(within(dialog).getByRole('tab', { name: 'General' })).toHaveFocus()
    await user.keyboard('{End}')
    expect(within(dialog).getByRole('tab', { name: 'General 2' })).toHaveFocus()
    await user.keyboard('{Home}')
    expect(within(dialog).getByRole('tab', { name: 'General' })).toHaveFocus()
    await user.keyboard('{End}')
    expect(within(dialog).getByRole('tab', { name: 'General 2' })).toHaveAttribute('tabindex', '0')
    expect(within(dialog).getByLabelText('Sex')).toHaveValue('female')
    expect(within(dialog).getByLabelText('Citizenship status')).toHaveValue('citizen')
    expect(within(dialog).getByLabelText('Employment Equity')).toHaveValue('Other/Unspecified')
    expect(within(dialog).getByLabelText('Employment Equity')).toBeEnabled()
    expect(within(dialog).getByLabelText('Other languages')).toHaveRole('listbox')
    expect(within(dialog).getByRole('option', { name: 'Historical Language' })).toBeInTheDocument()
    expect(within(dialog).getByRole('option', { name: 'Historical Type' })).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith('/api/candidates/decode-sa-id/', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ identity_number: idNumber }),
    }))
  })
})
