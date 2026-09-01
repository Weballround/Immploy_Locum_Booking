import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'


describe('Candidate profile editing', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('updates an active Candidate profile and multiple roles from the directory', async () => {
    const candidate = {
      id: 51,
      first_name: 'Nomsa',
      last_name: 'Directory',
      full_name: 'Nomsa Directory',
      email: 'before@example.test',
      phone: '0110000000',
      home_area: 'Rosebank',
      home_region: 'Gauteng',
      postal_code: '2000',
      is_active: true,
      compliance_status: 'cleared',
      profession_names: ['Registered Nurse'],
      profession_ids: [9],
    }
    const updatedCandidate = {
      ...candidate,
      email: 'after@example.test',
      phone: '0820000000',
      profession_names: ['Registered Nurse', 'Theatre Nurse'],
      profession_ids: [9, 10],
    }
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            authenticated: true,
            permissions: { manage_bookings: false, manage_candidates: true },
          }),
        })
      }
      if (url === '/api/candidates/' && !options?.method) {
        return Promise.resolve({ ok: true, json: async () => [candidate] })
      }
      if (url === '/api/candidates/51/profile/' && !options?.method) {
        return Promise.resolve({ ok: true, json: async () => ({
          ...candidate,
          preferred_name: '', date_of_birth: '', identity_number: '', is_sa_id: false,
          passport_number: '', visa_type: '', visa_start: '', visa_end: '', visa_selected: false,
          country_of_origin: '', nationality: '', home_language: '', is_locum: true,
          is_permanent: false, home_phone: '', other_contact: '', physical_address: '', note: '',
          division: '', assigned_consultant: '', sex: '', sex_source: '', citizenship_status: '',
          employment_equity: '', is_disabled: false, fingerprint_status: '', criminal_check: '',
          drivers_license: '', owns_car: false, qualification: '', qualification_types: [],
          education_level: '', source: '', marital_status: '', other_languages: [],
          can_set_compliance: false,
        }) })
      }
      if (url === '/api/candidates/creation-options/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            professions: [
              { id: 9, name: 'Registered Nurse' },
              { id: 10, name: 'Theatre Nurse' },
            ],
            locations: [
              { region: 'Gauteng', areas: ['Rosebank', 'Sandton'] },
              { region: 'Western Cape', areas: ['Cape Town'] },
            ],
          }),
        })
      }
      if (url === '/api/candidates/51/profile/' && options?.method === 'PATCH') {
        return Promise.resolve({ ok: true, json: async () => updatedCandidate })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: 'Edit Nomsa Directory' }))
    const dialog = await screen.findByRole('dialog', { name: 'Edit Nomsa Directory' })
    expect(within(dialog).getByLabelText('Compliance status')).toHaveTextContent('Cleared')
    expect(within(dialog).getByLabelText('Region')).toHaveRole('combobox')
    expect(within(dialog).getByLabelText('Area')).toHaveRole('combobox')
    expect(within(dialog).getByLabelText('Registered Nurse')).toBeChecked()
    expect(within(dialog).getByLabelText('Theatre Nurse')).not.toBeChecked()

    await user.clear(within(dialog).getByLabelText('Email'))
    await user.type(within(dialog).getByLabelText('Email'), 'after@example.test')
    await user.clear(within(dialog).getByLabelText('Cell phone'))
    await user.type(within(dialog).getByLabelText('Cell phone'), '0820000000')
    await user.click(within(dialog).getByLabelText('Theatre Nurse'))
    await user.click(within(dialog).getByRole('button', { name: 'Save candidate changes' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      '/api/candidates/51/profile/',
      expect.objectContaining({ method: 'PATCH' }),
    ))
    const updateCall = fetchMock.mock.calls.find(([url, options]) => (
      url === '/api/candidates/51/profile/' && options?.method === 'PATCH'
    ))
    expect(JSON.parse(String(updateCall?.[1]?.body))).toEqual(expect.objectContaining({
      first_name: 'Nomsa',
      last_name: 'Directory',
      email: 'after@example.test',
      phone: '0820000000',
      home_area: 'Rosebank',
      home_region: 'Gauteng',
      postal_code: '2000',
      is_active: true,
      profession_ids: [9, 10],
    }))
    expect(screen.queryByRole('dialog', { name: 'Edit Nomsa Directory' })).not.toBeInTheDocument()
    expect(await screen.findByText('Candidate profile updated')).toBeInTheDocument()
  })

  it('keeps save disabled when the restricted profile fails to load', async () => {
    const candidate = {
      id: 52, first_name: 'Load', last_name: 'Failure', full_name: 'Load Failure',
      email: '', phone: '', home_area: '', home_region: '', postal_code: '',
      is_active: true, compliance_status: 'pending', profession_names: ['Nurse'], profession_ids: [9],
    }
    const fetchMock = vi.fn((url: string) => {
      if (url === '/api/session/') return Promise.resolve({
        ok: true,
        json: async () => ({ authenticated: true, permissions: { manage_bookings: false, manage_candidates: true } }),
      })
      if (url === '/api/candidates/') return Promise.resolve({ ok: true, json: async () => [candidate] })
      if (url === '/api/candidates/52/profile/') return Promise.resolve({
        ok: false, status: 500, json: async () => ({ detail: 'Profile unavailable' }),
      })
      if (url === '/api/candidates/creation-options/') return Promise.resolve({
        ok: true,
        json: async () => ({ professions: [{ id: 9, name: 'Nurse' }], locations: [] }),
      })
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: 'Edit Load Failure' }))
    const dialog = await screen.findByRole('dialog', { name: 'Edit Load Failure' })

    await waitFor(() => expect(within(dialog).getByRole('button', { name: 'Save candidate changes' })).toBeDisabled())
    expect(fetchMock).not.toHaveBeenCalledWith(
      '/api/candidates/52/profile/',
      expect.objectContaining({ method: 'PATCH' }),
    )
  })
})
