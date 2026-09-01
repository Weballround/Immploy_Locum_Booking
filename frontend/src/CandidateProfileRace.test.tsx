import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

const candidate = (id: number, name: string) => ({
  id,
  first_name: name,
  last_name: 'Race',
  full_name: `${name} Race`,
  email: '',
  phone: '',
  home_area: '',
  home_region: '',
  postal_code: '',
  is_active: true,
  compliance_status: 'pending',
  profession_names: ['Nurse'],
  profession_ids: [9],
})

const profile = (entry: ReturnType<typeof candidate>) => ({
  ...entry,
  preferred_name: '', date_of_birth: '', identity_number: '', is_sa_id: false,
  passport_number: '', visa_type: '', visa_start: '', visa_end: '', visa_selected: false,
  country_of_origin: '', nationality: '', home_language: '', is_locum: true,
  is_permanent: false, home_phone: '', other_contact: '', physical_address: '', note: '',
  division: '', assigned_consultant: '', sex: '', sex_source: '', citizenship_status: '',
  employment_equity: '', is_disabled: false, fingerprint_status: '', criminal_check: '',
  drivers_license: '', owns_car: false, qualification: '', qualification_types: [],
  education_level: '', source: '', marital_status: '', other_languages: [],
  can_set_compliance: false,
})

const profileOptions = {
  countries: [], visa_types: [], languages: [], divisions: [], consultants: [],
  employment_equity: [], education_levels: [], qualifications: [], qualification_types: [],
  sources: [], marital_statuses: [], drivers_licenses: [], fingerprint_statuses: [],
  criminal_checks: [], sexes: [{ id: 'female', label: 'Female' }],
}

describe('Candidate profile request isolation', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('ignores profile and ID responses belonging to a previously opened Candidate', async () => {
    const alpha = candidate(71, 'Alpha')
    const beta = candidate(72, 'Beta')
    const firstAlphaProfile = deferred<{ ok: boolean; json: () => Promise<ReturnType<typeof profile>> }>()
    const betaDecode = deferred<{ ok: boolean; json: () => Promise<Record<string, string>> }>()
    let alphaProfileCalls = 0

    const fetchMock = vi.fn((url: string) => {
      if (url === '/api/session/') return Promise.resolve({
        ok: true,
        json: async () => ({ authenticated: true, permissions: { manage_bookings: false, manage_candidates: true } }),
      })
      if (url === '/api/candidates/') return Promise.resolve({ ok: true, json: async () => [alpha, beta] })
      if (url === '/api/candidates/creation-options/') return Promise.resolve({
        ok: true,
        json: async () => ({
          professions: [{ id: 9, name: 'Nurse' }],
          locations: [],
          profile: profileOptions,
        }),
      })
      if (url === '/api/candidates/71/profile/') {
        alphaProfileCalls += 1
        if (alphaProfileCalls === 1) return firstAlphaProfile.promise
        return Promise.resolve({ ok: true, json: async () => profile(alpha) })
      }
      if (url === '/api/candidates/72/profile/') {
        return Promise.resolve({ ok: true, json: async () => profile(beta) })
      }
      if (url === '/api/candidates/decode-sa-id/') return betaDecode.promise
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: 'Edit Alpha Race' }))
    await user.click(screen.getByRole('button', { name: 'Edit Beta Race' }))
    let dialog = await screen.findByRole('dialog', { name: 'Edit Beta Race' })
    await waitFor(() => expect(within(dialog).getByLabelText('First name')).toHaveValue('Beta'))

    firstAlphaProfile.resolve({ ok: true, json: async () => profile(alpha) })
    await waitFor(() => expect(within(dialog).getByLabelText('First name')).toHaveValue('Beta'))

    await user.click(within(dialog).getByLabelText('South African ID'))
    await user.type(within(dialog).getByLabelText('ID number'), '0001014000085')
    await user.tab()
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      '/api/candidates/decode-sa-id/',
      expect.objectContaining({ method: 'POST' }),
    ))

    await user.click(screen.getByRole('button', { name: 'Edit Alpha Race' }))
    dialog = await screen.findByRole('dialog', { name: 'Edit Alpha Race' })
    await waitFor(() => expect(within(dialog).getByLabelText('First name')).toHaveValue('Alpha'))

    betaDecode.resolve({
      ok: true,
      json: async () => ({
        date_of_birth: '2000-01-01', sex: 'female', sex_source: 'sa_id', citizenship_status: 'citizen',
      }),
    })
    await user.click(within(dialog).getByRole('tab', { name: 'General 2' }))
    await waitFor(() => expect(within(dialog).getByLabelText('Citizenship status')).toHaveValue('Not derived'))
    await user.click(within(dialog).getByRole('tab', { name: 'General' }))
    expect(within(dialog).getByLabelText('Date of birth')).toHaveValue('')
  })
})
