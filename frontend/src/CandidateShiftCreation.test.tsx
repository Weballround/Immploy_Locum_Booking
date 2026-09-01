import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'


describe('Candidate shift creation recovery', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('focuses the creation form and retries the failed stage without losing entered work', async () => {
    let creationOptionsAttempts = 0
    let siteRoleAttempts = 0
    const candidate = {
      id: 51,
      full_name: 'Nomsa Directory',
      compliance_status: 'cleared',
      home_area: 'Rosebank',
      home_region: 'Gauteng',
      profession_names: ['Registered Nurse'],
      profession_ids: [9],
    }
    const fetchMock = vi.fn((url: string) => {
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({ authenticated: true, permissions: { manage_bookings: true } }),
        })
      }
      if (url === '/api/shifts/') return Promise.resolve({ ok: true, json: async () => [] })
      if (url === '/api/candidates/') {
        return Promise.resolve({ ok: true, json: async () => [candidate] })
      }
      if (url === '/api/candidates/51/compatible-shifts/') {
        return Promise.resolve({ ok: true, json: async () => [] })
      }
      if (url === '/api/vacancies/creation-options/') {
        creationOptionsAttempts += 1
        if (creationOptionsAttempts === 1) {
          return Promise.resolve({ ok: false, status: 500, json: async () => ({}) })
        }
        return Promise.resolve({
          ok: true,
          json: async () => ({
            sites: [{ id: 7, name: 'Ward A', client_name: 'Rosebank Day Hospital' }],
            professions: [{ id: 9, name: 'Registered Nurse' }],
          }),
        })
      }
      if (url === '/api/vacancies/site-role-options/?site=7') {
        siteRoleAttempts += 1
        if (siteRoleAttempts === 1) {
          return Promise.resolve({ ok: false, status: 500, json: async () => ({}) })
        }
        return Promise.resolve({
          ok: true,
          json: async () => ({
            professions: [{ id: 9, name: 'Registered Nurse', pay_rate: '245.00', bill_rate: '455.00' }],
          }),
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: 'Candidates' }))
    await user.click(await screen.findByRole('button', { name: 'Book shifts for Nomsa Directory' }))
    const dialog = await screen.findByRole('dialog', { name: 'Book multiple shifts for Nomsa Directory' })
    await user.click(within(dialog).getByRole('button', { name: 'Create new shifts' }))

    const creationHeading = within(dialog).getByRole('heading', { name: 'Create and book new shifts' })
    expect(creationHeading).toHaveFocus()
    expect(await within(dialog).findByText('Could not load Facilities')).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Retry Facilities' }))
    await user.selectOptions(within(dialog).getByLabelText('Facility'), '7')

    expect(await within(dialog).findByText('Could not load Facility roles')).toBeInTheDocument()
    await user.type(within(dialog).getByLabelText('Reference (optional)'), 'CAND-RETRY')
    await user.type(within(dialog).getByLabelText('Shift 1 start'), '2026-09-10T07:00')
    await user.type(within(dialog).getByLabelText('Shift 1 end'), '2026-09-10T15:00')
    await user.click(within(dialog).getByRole('button', { name: 'Retry Facility roles' }))

    expect(within(dialog).getByLabelText('Facility')).toHaveValue('7')
    expect(within(dialog).getByLabelText('Reference (optional)')).toHaveValue('CAND-RETRY')
    expect(within(dialog).getByLabelText('Shift 1 start')).toHaveValue('2026-09-10T07:00')
    await user.selectOptions(within(dialog).getByLabelText('Role'), '9')
    expect(within(dialog).getByLabelText('Role')).toHaveValue('9')
  })
})
