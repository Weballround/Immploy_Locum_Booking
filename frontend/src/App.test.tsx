import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'

const openShift = {
  id: 1,
  site_id: 7,
  profession_id: 9,
  client_name: 'Rosebank Day Hospital',
  site_name: 'Ward A',
  profession_name: 'Registered Nurse',
  starts_at: '2026-08-07T07:30:00+02:00',
  ends_at: '2026-08-07T19:30:00+02:00',
  pay_rate: '210.00',
  bill_rate: '400.00',
  status: 'open',
  notes: '',
}

const secondOpenShift = {
  ...openShift,
  id: 2,
  site_id: 8,
  client_name: 'Sandton Hospital',
  site_name: 'Theatre 1',
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((resolvePromise) => { resolve = resolvePromise })
  return { promise, resolve }
}

describe('booking board', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url === '/api/session/') {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              authenticated: true,
              permissions: { manage_bookings: true, manage_candidates: true },
            }),
          })
        }
        if (url === '/api/shifts/') {
          return Promise.resolve({ ok: true, json: async () => [openShift] })
        }
        throw new Error(`Unexpected request: ${url}`)
      }),
    )
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('loads and displays open shifts', async () => {
    render(<App />)

    expect(screen.getByRole('heading', { name: 'Locum booking board' })).toBeInTheDocument()
    expect(await screen.findByText('Rosebank Day Hospital')).toBeInTheDocument()
    expect(screen.getByText('Registered Nurse')).toBeInTheDocument()
    expect(screen.getByText('Open')).toBeInTheDocument()
    expect(screen.queryByText('R210.00/hr pay')).not.toBeInTheDocument()
    expect(screen.queryByText('R400.00/hr charge')).not.toBeInTheDocument()
  })

  it('shows only the independently permitted commercial rate', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            authenticated: true,
            permissions: {
              manage_bookings: true,
              view_candidate_pay_rates: true,
              view_client_charge_rates: false,
            },
          }),
        })
      }
      if (url === '/api/shifts/') {
        return Promise.resolve({ ok: true, json: async () => [openShift] })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    await screen.findByText('Rosebank Day Hospital')
    expect(screen.getByText('R210.00/hr pay')).toBeInTheDocument()
    expect(screen.queryByText('R400.00/hr charge')).not.toBeInTheDocument()
  })

  it('opens an already filled booking and shows the confirmed candidate', async () => {
    const bookedShift = {
      ...openShift,
      status: 'booked',
      confirmed_booking: {
        id: 44,
        candidate_id: 71,
        candidate_name: 'Naledi Mokoena',
        status: 'confirmed',
      },
    }
    const fetchMock = vi.fn((url: string) => {
      if (url === '/api/shifts/') {
        return Promise.resolve({ ok: true, json: async () => [bookedShift] })
      }
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({ authenticated: true, permissions: { manage_bookings: true } }),
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: 'View booking' }))

    expect(screen.getByRole('heading', { name: 'Filled booking' })).toBeInTheDocument()
    expect(screen.getByText('Naledi Mokoena')).toBeInTheDocument()
    expect(screen.getByText('Confirmed candidate')).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalledWith('/api/shifts/1/candidates/')
    expect(screen.queryByRole('button', { name: 'Queue SMS' })).not.toBeInTheDocument()
  })

  it('previews, edits, and queues a booking confirmation SMS for an authorised scheduler', async () => {
    const bookedShift = {
      ...openShift,
      status: 'booked',
      confirmed_booking: {
        id: 44,
        candidate_id: 71,
        candidate_name: 'Naledi Mokoena',
        status: 'confirmed',
      },
    }
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
      if (url === '/api/shifts/') {
        return Promise.resolve({ ok: true, json: async () => [bookedShift] })
      }
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            authenticated: true,
            permissions: { manage_bookings: true, send_booking_sms: true },
          }),
        })
      }
      if (url === '/api/bookings/44/confirmation-sms/' && !options?.method) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            status: 'not_queued',
            destination: '+27821234567',
            body: 'Hello Naledi, your booking is confirmed.',
          }),
        })
      }
      if (url === '/api/bookings/44/confirmation-sms/' && options?.method === 'POST') {
        expect(JSON.parse(String(options.body))).toEqual({
          body: 'Edited SMS confirmation.',
        })
        return Promise.resolve({
          ok: true,
          json: async () => ({
            id: 91,
            status: 'queued',
            destination: '+27821234567',
            body: 'Edited SMS confirmation.',
          }),
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: 'View booking' }))
    const smsMessage = await screen.findByLabelText('SMS message')
    expect(smsMessage).toHaveValue('Hello Naledi, your booking is confirmed.')
    expect(screen.getByText('To +27821234567')).toBeInTheDocument()
    await user.clear(smsMessage)
    await user.type(smsMessage, 'Edited SMS confirmation.')
    await user.click(screen.getByRole('button', { name: 'Queue SMS' }))

    expect(await screen.findByText('SMS queued')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Queue SMS' })).not.toBeInTheDocument()
  })

  it('retries a failed booking SMS preview without closing the booking', async () => {
    const bookedShift = {
      ...openShift,
      status: 'booked',
      confirmed_booking: {
        id: 44,
        candidate_id: 71,
        candidate_name: 'Naledi Mokoena',
        status: 'confirmed',
      },
    }
    let previewAttempts = 0
    const fetchMock = vi.fn((url: string) => {
      if (url === '/api/shifts/') {
        return Promise.resolve({ ok: true, json: async () => [bookedShift] })
      }
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            authenticated: true,
            permissions: { manage_bookings: true, send_booking_sms: true },
          }),
        })
      }
      if (url === '/api/bookings/44/confirmation-sms/') {
        previewAttempts += 1
        if (previewAttempts === 1) {
          return Promise.resolve({
            ok: false,
            status: 503,
            json: async () => ({ detail: 'SMS preview is temporarily unavailable.' }),
          })
        }
        return Promise.resolve({
          ok: true,
          json: async () => ({
            status: 'not_queued',
            destination: '+278****4567',
            body: 'Recovered SMS preview.',
          }),
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: 'View booking' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('SMS preview is temporarily unavailable.')
    await user.click(screen.getByRole('button', { name: 'Retry SMS preview' }))

    expect(await screen.findByLabelText('SMS message')).toHaveValue('Recovered SMS preview.')
    expect(screen.getByRole('dialog', { name: 'Booking details' })).toHaveTextContent('Naledi Mokoena')
    expect(previewAttempts).toBe(2)
  })

  it('opens functional candidate, client, report, and booking navigation views', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === '/api/shifts/') {
        return Promise.resolve({ ok: true, json: async () => [openShift] })
      }
      if (url.startsWith('/api/shifts/?site=')) {
        return Promise.resolve({ ok: true, json: async () => [openShift] })
      }
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            authenticated: true,
            permissions: { manage_bookings: true },
          }),
        })
      }
      if (url === '/api/candidates/') {
        return Promise.resolve({
          ok: true,
          json: async () => [{
            id: 51,
            full_name: 'Nomsa Directory',
            compliance_status: 'cleared',
            home_area: 'Rosebank',
            home_region: 'Gauteng',
            profession_names: ['Registered Nurse'],
          }],
        })
      }
      if (url === '/api/vacancies/creation-options/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            sites: [{ id: 7, name: 'Ward A', client_name: 'Rosebank Day Hospital' }],
            professions: [{ id: 9, name: 'Registered Nurse' }],
          }),
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    expect(screen.getByRole('link', { name: 'IMMploy Recruitment' })).toHaveAttribute('href', '/')
    expect(screen.queryByRole('link', { name: 'Administration' })).not.toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'Sign out' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Candidates' }))
    expect(await screen.findByRole('heading', { name: 'Candidates' })).toBeInTheDocument()
    expect(await screen.findByText('Nomsa Directory')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Clients' }))
    expect(await screen.findByRole('heading', { name: 'Facilities' })).toBeInTheDocument()
    expect(await screen.findByText('Rosebank Day Hospital')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Reports' }))
    expect(await screen.findByRole('heading', { name: 'Coverage report' })).toBeInTheDocument()
    expect(screen.getByText('Requires placement')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Booking board' }))
    expect(screen.getByRole('heading', { name: 'Locum booking board' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Calendar' }))
    expect(await screen.findByRole('heading', { name: 'Facilities' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Facility calendar' })).toBeInTheDocument()
    expect(screen.getByRole('grid', { name: 'Rosebank Day Hospital Ward A calendar' })).toBeInTheDocument()
  })

  it('filters the Facility directory by client or Facility name', async () => {
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({ authenticated: true, permissions: { manage_bookings: true } }),
        })
      }
      if (url === '/api/shifts/') {
        return Promise.resolve({ ok: true, json: async () => [openShift, secondOpenShift] })
      }
      if (url === '/api/vacancies/creation-options/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            sites: [
              { id: 7, name: 'Ward A', client_name: 'Rosebank Day Hospital' },
              { id: 8, name: 'Theatre 1', client_name: 'Sandton Hospital' },
            ],
            professions: [{ id: 9, name: 'Registered Nurse' }],
          }),
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    }))
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: 'Clients' }))
    expect(await screen.findByText('Rosebank Day Hospital')).toBeInTheDocument()
    expect(screen.getByText('Sandton Hospital')).toBeInTheDocument()

    await user.type(screen.getByLabelText('Search facilities'), 'Theatre')

    expect(screen.queryByText('Rosebank Day Hospital')).not.toBeInTheDocument()
    expect(screen.getByText('Sandton Hospital')).toBeInTheDocument()
  })

  it('books one candidate into multiple compatible shifts from Candidates', async () => {
    const secondShift = {
      ...secondOpenShift,
      profession_id: 9,
      profession_name: 'Registered Nurse',
      starts_at: '2026-08-08T07:30:00+02:00',
      ends_at: '2026-08-08T19:30:00+02:00',
    }
    const directoryCandidate = {
      id: 51,
      full_name: 'Nomsa Directory',
      compliance_status: 'cleared',
      home_area: 'Rosebank',
      home_region: 'Gauteng',
      profession_names: ['Registered Nurse'],
      profession_ids: [9],
    }
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({ authenticated: true, permissions: { manage_bookings: true } }),
        })
      }
      if (url === '/api/shifts/') {
        return Promise.resolve({ ok: true, json: async () => [openShift, secondShift] })
      }
      if (url === '/api/candidates/') {
        return Promise.resolve({ ok: true, json: async () => [directoryCandidate] })
      }
      if (url === '/api/candidates/51/compatible-shifts/') {
        return Promise.resolve({ ok: true, json: async () => [openShift, secondShift] })
      }
      if (url === '/api/bookings/bulk/' && options?.method === 'POST') {
        return Promise.resolve({
          ok: true,
          status: 201,
          json: async () => [
            { id: 201, shift: 1, candidate: 51, status: 'confirmed' },
            { id: 202, shift: 2, candidate: 51, status: 'confirmed' },
          ],
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
    const checkboxes = within(dialog).getAllByRole('checkbox')
    await user.click(checkboxes[0])
    await user.click(checkboxes[1])
    await user.click(within(dialog).getByRole('button', { name: 'Book 2 shifts' }))

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/bookings/bulk/',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ assignments: [
          { shift: 1, candidate: 51, status: 'confirmed' },
          { shift: 2, candidate: 51, status: 'confirmed' },
        ] }),
      }),
    )
    expect(await screen.findByText('2 bookings confirmed')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Book shifts for Nomsa Directory' }))
    const reopenedDialog = await screen.findByRole('dialog', { name: 'Book multiple shifts for Nomsa Directory' })
    expect(within(reopenedDialog).getByRole('button', { name: 'Close multiple booking' })).toBeEnabled()
  })

  it('uses one-minute booking times for a Permanent-desk Candidate workflow', async () => {
    const directoryCandidate = {
      id: 51,
      full_name: 'Nomsa Directory',
      compliance_status: 'cleared',
      home_area: 'Rosebank',
      home_region: 'Gauteng',
      profession_names: ['Registered Nurse'],
      profession_ids: [9],
    }
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            authenticated: true,
            booking_time_step_seconds: 60,
            permissions: { manage_bookings: true },
          }),
        })
      }
      if (url === '/api/shifts/') return Promise.resolve({ ok: true, json: async () => [] })
      if (url === '/api/candidates/') {
        return Promise.resolve({ ok: true, json: async () => [directoryCandidate] })
      }
      if (url === '/api/candidates/51/compatible-shifts/') {
        return Promise.resolve({ ok: true, json: async () => [] })
      }
      if (url === '/api/vacancies/creation-options/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            sites: [{ id: 7, name: 'Ward A', client_name: 'Rosebank Day Hospital' }],
            professions: [{ id: 9, name: 'Registered Nurse' }],
          }),
        })
      }
      if (url === '/api/vacancies/site-role-options/?site=7') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            professions: [{ id: 9, name: 'Registered Nurse', pay_rate: '245.00', bill_rate: '455.00' }],
          }),
        })
      }
      if (url === '/api/vacancies/book-candidate-shifts/' && options?.method === 'POST') {
        return Promise.resolve({
          ok: true,
          status: 201,
          json: async () => ({ vacancy: { id: 80, reference: '', shifts: [] }, bookings: [{ id: 1 }, { id: 2 }] }),
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
    expect(within(dialog).getByText('No compatible open shifts are available.')).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Create new shifts' }))
    await user.selectOptions(within(dialog).getByLabelText('Facility'), '7')
    await user.selectOptions(await within(dialog).findByLabelText('Role'), '9')
    const firstStart = within(dialog).getByLabelText('Shift 1 start')
    const firstEnd = within(dialog).getByLabelText('Shift 1 end')
    expect(firstStart).toHaveAttribute('step', '60')
    expect(firstEnd).toHaveAttribute('step', '60')
    await user.type(firstStart, '2026-09-10T07:07')
    expect(firstEnd).toHaveValue('2026-09-10T14:07')
    await user.click(within(dialog).getByRole('button', { name: 'Add another shift' }))
    await user.type(within(dialog).getByLabelText('Shift 2 start'), '2026-09-11T07:08')
    expect(within(dialog).getByLabelText('Shift 2 end')).toHaveValue('2026-09-11T14:08')
    await user.click(within(dialog).getByRole('button', { name: 'Create and book 2 shifts' }))

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/vacancies/book-candidate-shifts/',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          candidate: 51,
          site: 7,
          profession: 9,
          reference: '',
          notes: '',
          shift_items: [
            { starts_at: '2026-09-10T07:07', ends_at: '2026-09-10T14:07' },
            { starts_at: '2026-09-11T07:08', ends_at: '2026-09-11T14:08' },
          ],
        }),
      }),
    )
    expect(await screen.findByText('2 new shifts booked for Nomsa Directory')).toBeInTheDocument()
  })

  it('assigns multiple eligible candidates across Facility shifts atomically', async () => {
    const secondShift = {
      ...secondOpenShift,
      site_id: 7,
      client_name: 'Rosebank Day Hospital',
      site_name: 'Ward A',
      profession_id: 10,
      profession_name: 'Medical Doctor',
      starts_at: '2026-08-08T08:00:00+02:00',
      ends_at: '2026-08-08T16:00:00+02:00',
    }
    const nurse = { id: 51, full_name: 'Nomsa Nurse', role_name: 'Registered Nurse' }
    const doctor = { id: 52, full_name: 'Dineo Doctor', role_name: 'Medical Doctor' }
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({ authenticated: true, permissions: { manage_bookings: true } }),
        })
      }
      if (url === '/api/shifts/') {
        return Promise.resolve({ ok: true, json: async () => [openShift, secondShift] })
      }
      if (url.startsWith('/api/shifts/?site=7&')) {
        return Promise.resolve({ ok: true, json: async () => [openShift, secondShift] })
      }
      if (url === '/api/vacancies/creation-options/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            sites: [{ id: 7, name: 'Ward A', client_name: 'Rosebank Day Hospital' }],
            professions: [
              { id: 9, name: 'Registered Nurse' },
              { id: 10, name: 'Medical Doctor' },
            ],
          }),
        })
      }
      if (url === '/api/shifts/1/candidates/') {
        return Promise.resolve({ ok: true, json: async () => [nurse] })
      }
      if (url === '/api/shifts/2/candidates/') {
        return Promise.resolve({ ok: true, json: async () => [doctor] })
      }
      if (url === '/api/bookings/bulk/' && options?.method === 'POST') {
        return Promise.resolve({
          ok: true,
          status: 201,
          json: async () => [
            { id: 301, shift: 1, candidate: 51, status: 'confirmed' },
            { id: 302, shift: 2, candidate: 52, status: 'confirmed' },
          ],
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: 'Clients' }))
    await user.click(await screen.findByRole('button', { name: 'View calendar for Rosebank Day Hospital Ward A' }))
    await user.click(await screen.findByRole('button', { name: 'Multiple booking for Rosebank Day Hospital Ward A' }))
    const dialog = await screen.findByRole('dialog', { name: 'Create multiple bookings for Rosebank Day Hospital Ward A' })
    const nurseSelector = within(dialog).getByRole('combobox', {
      name: /Eligible candidate for Shift 1, Registered Nurse/,
    })
    const doctorSelector = within(dialog).getByRole('combobox', {
      name: /Eligible candidate for Shift 2, Medical Doctor/,
    })
    await user.selectOptions(nurseSelector, '51')
    await user.selectOptions(doctorSelector, '52')
    await user.click(within(dialog).getByRole('button', { name: 'Book 2 assignments' }))

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/bookings/bulk/',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ assignments: [
          { shift: 1, candidate: 51, status: 'confirmed' },
          { shift: 2, candidate: 52, status: 'confirmed' },
        ] }),
      }),
    )
    expect(await screen.findByText('2 bookings confirmed')).toBeInTheDocument()
  })

  it('retries failed Facility eligible-candidate matching without losing selected shifts', async () => {
    let candidateAttempts = 0
    const candidate = { id: 51, full_name: 'Nomsa Nurse', role_name: 'Registered Nurse' }
    const fetchMock = vi.fn((url: string) => {
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({ authenticated: true, permissions: { manage_bookings: true } }),
        })
      }
      if (url === '/api/shifts/') {
        return Promise.resolve({ ok: true, json: async () => [openShift] })
      }
      if (url.startsWith('/api/shifts/?site=7&')) {
        return Promise.resolve({ ok: true, json: async () => [openShift] })
      }
      if (url === '/api/vacancies/creation-options/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            sites: [{ id: 7, name: 'Ward A', client_name: 'Rosebank Day Hospital' }],
            professions: [{ id: 9, name: 'Registered Nurse' }],
          }),
        })
      }
      if (url === '/api/shifts/1/candidates/') {
        candidateAttempts += 1
        return Promise.resolve(candidateAttempts === 1
          ? { ok: false, status: 503 }
          : { ok: true, json: async () => [candidate] })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: 'Clients' }))
    await user.click(await screen.findByRole('button', { name: 'View calendar for Rosebank Day Hospital Ward A' }))
    await user.click(await screen.findByRole('button', { name: 'Multiple booking for Rosebank Day Hospital Ward A' }))
    expect(await screen.findByText('Could not load eligible candidates')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Retry matching' }))

    expect(await screen.findByRole('combobox', {
      name: /Eligible candidate for Shift 1, Registered Nurse.*Fri, 07 Aug, 07:30/,
    })).toHaveTextContent('Nomsa Nurse')
    expect(candidateAttempts).toBe(2)
  })

  it('updates the Facility calendar to booking details after a direct booking', async () => {
    const candidate = { id: 51, full_name: 'Nomsa Nurse', role_name: 'Registered Nurse' }
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({ authenticated: true, permissions: { manage_bookings: true } }),
        })
      }
      if (url === '/api/shifts/') {
        return Promise.resolve({ ok: true, json: async () => [openShift] })
      }
      if (url.startsWith('/api/shifts/?site=7&')) {
        return Promise.resolve({ ok: true, json: async () => [openShift] })
      }
      if (url === '/api/vacancies/creation-options/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            sites: [{ id: 7, name: 'Ward A', client_name: 'Rosebank Day Hospital' }],
            professions: [{ id: 9, name: 'Registered Nurse' }],
          }),
        })
      }
      if (url === '/api/shifts/1/candidates/') {
        return Promise.resolve({ ok: true, json: async () => [candidate] })
      }
      if (url === '/api/bookings/' && options?.method === 'POST') {
        return Promise.resolve({
          ok: true,
          status: 201,
          json: async () => ({ id: 501, shift: 1, candidate: 51, status: 'confirmed' }),
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: 'Clients' }))
    await user.click(await screen.findByRole('button', { name: 'View calendar for Rosebank Day Hospital Ward A' }))
    const openCalendarShift = await screen.findByRole('button', {
      name: /Open Registered Nurse shift.*Add candidate/,
    })
    await user.click(openCalendarShift)
    await user.click(await screen.findByRole('button', { name: 'Add Nomsa Nurse to booking' }))

    const bookedCalendarShift = await screen.findByRole('button', {
      name: /Booked Registered Nurse shift.*Open booking details/,
    })
    expect(bookedCalendarShift).toBeInTheDocument()
    expect(screen.queryByRole('button', {
      name: /Open Registered Nurse shift.*Add candidate/,
    })).not.toBeInTheDocument()
    await user.click(bookedCalendarShift)
    expect(await screen.findByRole('dialog', { name: 'Booking details' })).toHaveTextContent('Nomsa Nurse')
  })

  it('shows a Johannesburg calendar using facility and month-scoped shift requests', async () => {
    const boundaryShift = {
      ...openShift,
      profession_name: 'Emergency Nurse',
      starts_at: '2026-08-31T22:30:00Z',
      ends_at: '2026-09-01T10:30:00Z',
    }
    const overnightShift = {
      ...openShift,
      id: 3,
      profession_name: 'Night Nurse',
      starts_at: '2026-09-01T17:30:00Z',
      ends_at: '2026-09-02T05:30:00Z',
    }
    const secondEmergencyShift = {
      ...boundaryShift,
      id: 4,
      starts_at: '2026-09-01T00:00:00Z',
      ends_at: '2026-09-01T02:00:00Z',
    }
    const sandtonShift = { ...secondOpenShift, profession_name: 'Theatre Nurse' }
    const octoberShift = {
      ...openShift,
      id: 5,
      profession_name: 'October Nurse',
      starts_at: '2026-10-02T06:00:00Z',
      ends_at: '2026-10-02T14:00:00Z',
    }
    const fetchMock = vi.fn((url: string) => {
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({ authenticated: true, permissions: { manage_bookings: true } }),
        })
      }
      if (url === '/api/shifts/') {
        return Promise.resolve({ ok: true, json: async () => [boundaryShift, sandtonShift] })
      }
      if (url.startsWith('/api/shifts/?')) {
        const params = new URL(url, 'http://localhost').searchParams
        const site = params.get('site')
        const endsAfter = params.get('ends_after')
        return Promise.resolve({
          ok: true,
          json: async () => site === '7'
            ? endsAfter === '2026-10-01T00:00:00+02:00'
              ? [octoberShift]
              : [boundaryShift, overnightShift, secondEmergencyShift]
            : [sandtonShift],
        })
      }
      if (url === '/api/vacancies/creation-options/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            sites: [
              { id: 7, name: 'Ward A', client_name: 'Rosebank Day Hospital' },
              { id: 8, name: 'Theatre 1', client_name: 'Sandton Hospital' },
            ],
            professions: [{ id: 9, name: 'Registered Nurse' }],
          }),
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: 'Clients' }))
    await user.click(await screen.findByRole('button', {
      name: 'View calendar for Rosebank Day Hospital Ward A',
    }))

    expect(await screen.findByRole('heading', { name: 'September 2026' })).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/^\/api\/shifts\/\?site=7&starts_before=.*&ends_after=.*/),
      { credentials: 'same-origin' },
    )
    expect(screen.getAllByText('Emergency Nurse')).toHaveLength(2)
    expect(screen.getByText('Night Nurse')).toBeInTheDocument()
    expect(screen.getAllByText('Open')).toHaveLength(3)
    expect(screen.getByText('00:30 – 12:30')).toBeInTheDocument()
    expect(screen.getByText('19:30 – 2 Sept, 07:30')).toBeInTheDocument()
    expect(screen.getByRole('button', {
      name: /Open Emergency Nurse shift.*00:30 – 12:30.*Add candidate/,
    })).toBeInTheDocument()
    expect(screen.getByRole('button', {
      name: /Open Emergency Nurse shift.*02:00 – 04:00.*Add candidate/,
    })).toBeInTheDocument()
    expect(screen.queryByText('Theatre Nurse')).not.toBeInTheDocument()

    const rows = screen.getAllByRole('row')
    expect(rows).toHaveLength(7)
    const firstSeptember = screen.getByRole('gridcell', { name: /Tuesday, 1 September 2026/ })
    const secondSeptember = screen.getByRole('gridcell', { name: /Wednesday, 2 September 2026/ })
    firstSeptember.focus()
    await user.keyboard('{ArrowRight}')
    expect(secondSeptember).toHaveFocus()

    await user.click(screen.getByRole('button', { name: 'Next month' }))
    expect(await screen.findByRole('heading', { name: 'October 2026' })).toBeInTheDocument()
    expect(await screen.findByText('October Nurse')).toBeInTheDocument()
    expect(screen.queryByText('Emergency Nurse')).not.toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([url]) => {
      if (typeof url !== 'string' || !url.startsWith('/api/shifts/?')) return false
      const params = new URL(url, 'http://localhost').searchParams
      return params.get('site') === '7'
        && params.get('ends_after') === '2026-10-01T00:00:00+02:00'
        && params.get('starts_before') === '2026-11-01T00:00:00+02:00'
    })).toBe(true)
    await user.click(screen.getByRole('button', { name: 'Previous month' }))
    expect(await screen.findByRole('heading', { name: 'September 2026' })).toBeInTheDocument()
    expect(await screen.findAllByText('Emergency Nurse')).toHaveLength(2)

    await user.selectOptions(screen.getByRole('combobox', { name: 'Facility' }), '8')
    expect(await screen.findByText('Theatre Nurse')).toBeInTheDocument()
    expect(screen.queryByText('Emergency Nurse')).not.toBeInTheDocument()
  })

  it('restores Calendar context when retrying a failed Facility-list request', async () => {
    let facilityAttempts = 0
    const fetchMock = vi.fn((url: string) => {
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({ authenticated: true, permissions: { manage_bookings: true } }),
        })
      }
      if (url === '/api/shifts/') {
        return Promise.resolve({ ok: true, json: async () => [openShift] })
      }
      if (url === '/api/vacancies/creation-options/') {
        facilityAttempts += 1
        return Promise.resolve(facilityAttempts === 1
          ? { ok: false, status: 503 }
          : {
              ok: true,
              json: async () => ({
                sites: [{ id: 7, name: 'Ward A', client_name: 'Rosebank Day Hospital' }],
                professions: [{ id: 9, name: 'Registered Nurse' }],
              }),
            })
      }
      if (url.startsWith('/api/shifts/?site=7&')) {
        return Promise.resolve({ ok: true, json: async () => [] })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: 'Calendar' }))
    expect(await screen.findByText('Could not load facilities')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Retry facilities' }))

    expect(await screen.findByRole('grid', {
      name: 'Rosebank Day Hospital Ward A calendar',
    })).toBeInTheDocument()
    expect(facilityAttempts).toBe(2)
  })

  it('does not carry a candidate loading error into cached facilities', async () => {
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      if (url === '/api/shifts/') {
        return Promise.resolve({ ok: true, json: async () => [openShift] })
      }
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({ authenticated: true, permissions: { manage_bookings: true } }),
        })
      }
      if (url === '/api/vacancies/creation-options/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            sites: [{ id: 7, name: 'Ward A', client_name: 'Cached Hospital' }],
            professions: [],
          }),
        })
      }
      if (url === '/api/candidates/') return Promise.resolve({ ok: false, status: 500 })
      throw new Error(`Unexpected request: ${url}`)
    }))
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: 'Clients' }))
    expect(await screen.findByText('Cached Hospital')).toBeInTheDocument()
    await user.click(await screen.findByRole('button', { name: 'Candidates' }))
    expect(await screen.findByText('Could not load candidates')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Clients' }))

    expect(await screen.findByText('Cached Hospital')).toBeInTheDocument()
    expect(screen.queryByText('Could not load candidates')).not.toBeInTheDocument()
  })

  it('books now from a preselected Facility with quarter-hour times and a seven-hour end time', async () => {
    const bookedShift = {
      ...openShift,
      id: 18,
      starts_at: '2026-09-12T20:00:00+02:00',
      ends_at: '2026-09-13T03:00:00+02:00',
      status: 'booked' as const,
      confirmed_booking: {
        id: 44,
        candidate_id: 71,
        candidate_name: 'Ava Worked',
        status: 'confirmed' as const,
      },
    }
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
      if (url === '/api/shifts/' && !options?.method) {
        return Promise.resolve({ ok: true, json: async () => [openShift] })
      }
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            authenticated: true,
            permissions: { manage_bookings: true },
          }),
        })
      }
      if (url === '/api/vacancies/creation-options/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            sites: [{ id: 7, name: 'Ward A', client_name: 'Rosebank Day Hospital' }],
            professions: [{ id: 9, name: 'Registered Nurse' }],
          }),
        })
      }
      if (url === '/api/vacancies/site-role-options/?site=7') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            professions: [{
              id: 9,
              name: 'Registered Nurse',
              pay_rate: '210.00',
              bill_rate: '400.00',
            }],
          }),
        })
      }
      if (url === '/api/candidates/?search=&profession=9&site=7&starts_at=2026-09-12T20%3A00%3A00&ends_at=2026-09-13T03%3A00%3A00') {
        return Promise.resolve({
          ok: true,
          json: async () => [{
            id: 71,
            full_name: 'Ava Worked',
            compliance_status: 'cleared',
            home_area: 'Sandton',
            home_region: 'Gauteng',
            profession_names: ['Registered Nurse'],
            worked_at_facility: true,
            facility_shift_count: 3,
            proximity_label: 'Same town as facility',
          }],
        })
      }
      if (url === '/api/vacancies/book-now/' && options?.method === 'POST') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            vacancy: { id: 17, reference: '', shifts: [bookedShift] },
            booking: { id: 44, shift: 18, candidate: 71, status: 'confirmed' },
          }),
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: 'Clients' }))
    await user.click(await screen.findByRole('button', {
      name: 'Book now for Rosebank Day Hospital Ward A',
    }))
    const dialog = screen.getByRole('dialog', { name: 'Book now' })
    const heading = within(dialog).getByRole('heading', { name: 'Book now' })
    expect(heading).toHaveFocus()
    await user.keyboard('{Shift>}{Tab}{/Shift}')
    expect(within(dialog).getByRole('button', { name: 'Cancel' })).toHaveFocus()
    heading.focus()
    await user.tab()
    expect(within(dialog).getByRole('button', { name: 'Close new vacancy form' })).toHaveFocus()
    expect(screen.getByLabelText('Facility')).toHaveValue('7')
    expect(screen.getByLabelText('Facility')).toBeDisabled()
    await user.selectOptions(await screen.findByLabelText('Role'), '9')
    expect(screen.getByLabelText('Start 1')).toHaveAttribute('step', '900')
    expect(screen.getByLabelText('End 1')).toHaveAttribute('step', '900')
    await user.type(screen.getByLabelText('Start 1'), '2026-09-12T20:00')
    expect(screen.getByLabelText('End 1')).toHaveValue('2026-09-13T03:00')
    await user.selectOptions(await screen.findByLabelText('Candidate'), '71')
    await user.click(screen.getByRole('button', { name: 'Create vacancy and book' }))

    expect(await screen.findByText('Vacancy created and Ava Worked booked')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/vacancies/book-now/',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          reference: '',
          site: 7,
          profession: 9,
          notes: '',
          candidate: 71,
          starts_at: '2026-09-12T20:00:00',
          ends_at: '2026-09-13T03:00:00',
        }),
      }),
    )
  })

  it('retries Book now role and candidate loading without losing the form', async () => {
    let roleAttempts = 0
    let candidateAttempts = 0
    const candidateUrl = '/api/candidates/?search=&profession=9&site=7&starts_at=2026-09-12T08%3A00%3A00&ends_at=2026-09-12T15%3A00%3A00'
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
      if (url === '/api/shifts/' && !options?.method) {
        return Promise.resolve({ ok: true, json: async () => [openShift] })
      }
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            authenticated: true,
            permissions: { manage_bookings: true },
          }),
        })
      }
      if (url === '/api/vacancies/creation-options/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            sites: [{ id: 7, name: 'Ward A', client_name: 'Rosebank Day Hospital' }],
            professions: [{ id: 9, name: 'Registered Nurse' }],
          }),
        })
      }
      if (url === '/api/vacancies/site-role-options/?site=7') {
        roleAttempts += 1
        if (roleAttempts === 1) return Promise.resolve({ ok: false })
        return Promise.resolve({
          ok: true,
          json: async () => ({
            professions: [{ id: 9, name: 'Registered Nurse', pay_rate: '210.00', bill_rate: '400.00' }],
          }),
        })
      }
      if (url === candidateUrl) {
        candidateAttempts += 1
        if (candidateAttempts === 1) return Promise.resolve({ ok: false })
        return Promise.resolve({
          ok: true,
          json: async () => [{
            id: 71,
            full_name: 'Retry Candidate',
            compliance_status: 'cleared',
            home_area: 'Sandton',
            home_region: 'Gauteng',
            profession_names: ['Registered Nurse'],
            worked_at_facility: false,
            facility_shift_count: 0,
            proximity_label: 'Same town as facility',
          }],
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: 'Clients' }))
    await user.click(await screen.findByRole('button', {
      name: 'Book now for Rosebank Day Hospital Ward A',
    }))
    expect(await screen.findByText('Could not load roles for this facility.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Retry roles' }))
    await user.selectOptions(await screen.findByLabelText('Role'), '9')
    await user.type(screen.getByLabelText('Start 1'), '2026-09-12T08:00')

    expect(await screen.findByText('Could not load matching candidates')).toBeInTheDocument()
    expect(screen.queryByText('No compliance-cleared matching candidates')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Facility')).toHaveValue('7')
    expect(screen.getByLabelText('Start 1')).toHaveValue('2026-09-12T08:00')
    await user.click(screen.getByRole('button', { name: 'Retry candidates' }))

    expect(await screen.findByRole('option', { name: /Retry Candidate/ })).toBeInTheDocument()
    expect(screen.queryByText('Could not load matching candidates')).not.toBeInTheDocument()
  })

  it('adds a local candidate as pending compliance', async () => {
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
      if (url === '/api/shifts/') {
        return Promise.resolve({ ok: true, json: async () => [openShift] })
      }
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            authenticated: true,
            permissions: { manage_bookings: true, manage_candidates: true },
          }),
        })
      }
      if (url === '/api/candidates/' && !options?.method) {
        return Promise.resolve({ ok: true, json: async () => [] })
      }
      if (url === '/api/candidates/creation-options/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            sites: [],
            professions: [{ id: 9, name: 'Locum Pharmacist' }],
            locations: [
              { region: 'Gauteng', areas: ['Rosebank', 'Sandton'] },
              { region: 'Western Cape', areas: ['Cape Town'] },
            ],
          }),
        })
      }
      if (url === '/api/candidates/' && options?.method === 'POST') {
        return Promise.resolve({
          ok: true,
          status: 201,
          json: async () => ({
            id: 71,
            full_name: 'Naledi Mokoena',
            compliance_status: 'pending',
            home_area: 'Sandton',
            home_region: 'Gauteng',
            profession_names: ['Locum Pharmacist'],
          }),
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: 'Candidates' }))
    await user.click(await screen.findByRole('button', { name: 'Add candidate' }))
    await user.type(screen.getByLabelText('First name'), 'Naledi')
    await user.type(screen.getByLabelText('Last name'), 'Mokoena')
    expect(screen.getByLabelText('Region')).toHaveRole('combobox')
    expect(screen.getByLabelText('Region')).toHaveValue('Western Cape')
    expect(screen.getByLabelText('Area')).toHaveRole('combobox')
    await user.selectOptions(screen.getByLabelText('Region'), 'Gauteng')
    expect(screen.queryByRole('option', { name: 'Cape Town' })).not.toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('Area'), 'Sandton')
    await user.selectOptions(screen.getByLabelText('Candidate role'), '9')
    await user.click(screen.getByRole('button', { name: 'Save candidate' }))

    expect(await screen.findByText('Naledi Mokoena')).toBeInTheDocument()
    expect(screen.getByText('pending')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/candidates/',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          first_name: 'Naledi',
          last_name: 'Mokoena',
          home_area: 'Sandton',
          home_region: 'Gauteng',
          profession_ids: [9],
        }),
      }),
    )
  })

  it('creates a vacancy with multiple shifts from the Add vacancy button', async () => {
    const firstCreatedShift = {
      ...openShift,
      id: 3,
      client_name: 'New Shift Hospital',
      site_name: 'Ward N',
      profession_name: 'ICU Nurse',
    }
    const secondCreatedShift = {
      ...firstCreatedShift,
      id: 4,
      starts_at: '2026-09-13T06:00:00+02:00',
      ends_at: '2026-09-13T18:00:00+02:00',
    }
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
      if (url === '/api/shifts/' && !options?.method) {
        return Promise.resolve({ ok: true, json: async () => [openShift] })
      }
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            authenticated: true,
            permissions: {
              manage_bookings: true,
              view_candidate_pay_rates: true,
              override_approved_rates: true,
            },
          }),
        })
      }
      if (url === '/api/vacancies/creation-options/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            sites: [
              { id: 6, name: 'Ward A', client_name: 'Rosebank Hospital' },
              { id: 7, name: 'Ward N', client_name: 'New Shift Hospital' },
            ],
            professions: [{ id: 9, name: 'ICU Nurse' }],
          }),
        })
      }
      if (url === '/api/vacancies/site-role-options/?site=7') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            professions: [{
              id: 9,
              name: 'ICU Nurse',
              pay_rate: '225.00',
              bill_rate: '425.00',
            }],
          }),
        })
      }
      if (url === '/api/vacancies/' && options?.method === 'POST') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            id: 12,
            reference: 'Weekend cover',
            shifts: [firstCreatedShift, secondCreatedShift],
          }),
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    await screen.findByText('Rosebank Day Hospital')
    const addVacancy = await screen.findByRole('button', { name: /Add vacancy/ })
    expect(addVacancy.closest('.board-panel')).not.toBeNull()
    expect(addVacancy.closest('.topbar')).toBeNull()
    await user.click(addVacancy)
    expect(await screen.findByRole('heading', { name: 'Create vacancy' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Bill rate')).not.toBeInTheDocument()
    await user.type(screen.getByLabelText('Reference'), 'Weekend cover')
    await user.type(screen.getByLabelText('Search facilities'), 'New Shift')
    expect(screen.queryByRole('option', { name: 'Rosebank Hospital · Ward A' })).not.toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'New Shift Hospital · Ward N' })).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('Facility'), '7')
    await user.selectOptions(screen.getByLabelText('Role'), '9')
    await user.type(screen.getByLabelText('Start 1'), '2026-09-12T06:00')
    expect(screen.getByLabelText('End 1')).toHaveValue('2026-09-12T13:00')
    await user.clear(screen.getByLabelText('End 1'))
    await user.type(screen.getByLabelText('End 1'), '2026-09-12T18:00')
    await user.click(screen.getByRole('button', { name: 'Add another shift' }))
    await user.type(screen.getByLabelText('Start 2'), '2026-09-13T06:00')
    expect(screen.getByLabelText('End 2')).toHaveValue('2026-09-13T13:00')
    await user.clear(screen.getByLabelText('End 2'))
    await user.type(screen.getByLabelText('End 2'), '2026-09-13T18:00')
    expect(screen.getByLabelText('Pay rate')).toHaveValue(225)
    await user.type(screen.getByLabelText('Notes'), 'Urgent fill')
    await user.click(screen.getByRole('button', { name: 'Create vacancy' }))

    await user.click(screen.getByRole('button', { name: 'Booking board' }))
    expect((await screen.findAllByText('New Shift Hospital')).length).toBe(2)
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/vacancies/',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          reference: 'Weekend cover',
          site: 7,
          profession: 9,
          notes: 'Urgent fill',
          shift_items: [
            {
              starts_at: '2026-09-12T06:00:00',
              ends_at: '2026-09-12T18:00:00',
              pay_rate: '225.00',
            },
            {
              starts_at: '2026-09-13T06:00:00',
              ends_at: '2026-09-13T18:00:00',
              pay_rate: '225.00',
            },
          ],
        }),
      }),
    )
  })

  it('shows the backend validation reason when vacancy creation fails', async () => {
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({ authenticated: true, permissions: { manage_bookings: true } }),
        })
      }
      if (url === '/api/shifts/') {
        return Promise.resolve({ ok: true, json: async () => [openShift] })
      }
      if (url === '/api/vacancies/creation-options/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            sites: [{ id: 427, name: 'Main facility', client_name: 'Mediclinic Durbanville' }],
            professions: [{ id: 322, name: 'Nurse RN - Midwife' }],
          }),
        })
      }
      if (url === '/api/vacancies/site-role-options/?site=427') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            professions: [{ id: 322, name: 'Nurse RN - Midwife', pay_rate: '187.58' }],
          }),
        })
      }
      if (url === '/api/vacancies/' && options?.method === 'POST') {
        return Promise.resolve({
          ok: false,
          status: 400,
          json: async () => ({ shift_items: [{ pay_rate: ['A valid number is required.'] }] }),
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: /Add vacancy/ }))
    await user.type(screen.getByLabelText('Reference'), 'New One')
    await user.selectOptions(screen.getByLabelText('Facility'), '427')
    await user.selectOptions(await screen.findByLabelText('Role'), '322')
    expect(screen.queryByLabelText('Pay rate')).not.toBeInTheDocument()
    await user.type(screen.getByLabelText('Start 1'), '2026-08-07T06:00')
    await user.clear(screen.getByLabelText('End 1'))
    await user.type(screen.getByLabelText('End 1'), '2026-08-07T18:00')
    await user.click(screen.getByRole('button', { name: 'Create vacancy' }))

    expect(await screen.findByText('A valid number is required.')).toBeInTheDocument()
    const createCall = fetchMock.mock.calls.find(
      ([url, options]) => url === '/api/vacancies/' && options?.method === 'POST',
    )
    expect(createCall).toBeDefined()
    expect(JSON.parse(String(createCall?.[1]?.body)).shift_items).toEqual([{
      starts_at: '2026-08-07T06:00:00',
      ends_at: '2026-08-07T18:00:00',
    }])
    await user.type(screen.getByLabelText('Notes'), 'Corrected configuration')
    expect(screen.queryByText('A valid number is required.')).not.toBeInTheDocument()
  })

  it('moves focus into the vacancy dialog and restores it after Escape', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({ authenticated: true, permissions: { manage_bookings: true } }),
        })
      }
      if (url === '/api/shifts/') {
        return Promise.resolve({ ok: true, json: async () => [openShift] })
      }
      if (url === '/api/vacancies/creation-options/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({ sites: [], professions: [] }),
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    const trigger = await screen.findByRole('button', { name: /Add vacancy/ })
    await user.click(trigger)

    const dialog = await screen.findByRole('dialog', { name: 'Create vacancy' })
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    await waitFor(() => expect(screen.getByLabelText('Reference')).toHaveFocus())

    await user.keyboard('{Escape}')

    expect(screen.queryByRole('dialog', { name: 'Create vacancy' })).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it('ignores a delayed vacancy response after sign-out clears operational state', async () => {
    const vacancyResponse = deferred<{
      ok: boolean
      json: () => Promise<{ id: number; reference: string; shifts: typeof openShift[] }>
    }>()
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
      if (url === '/api/session/' && options?.method === 'DELETE') {
        return Promise.resolve({ ok: true, json: async () => ({}) })
      }
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({ authenticated: true, permissions: { manage_bookings: true } }),
        })
      }
      if (url === '/api/shifts/') {
        return Promise.resolve({ ok: true, json: async () => [openShift] })
      }
      if (url === '/api/vacancies/creation-options/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            sites: [{ id: 7, name: 'Ward N', client_name: 'New Shift Hospital' }],
            professions: [{ id: 9, name: 'ICU Nurse' }],
          }),
        })
      }
      if (url === '/api/vacancies/site-role-options/?site=7') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            professions: [{ id: 9, name: 'ICU Nurse', pay_rate: '225.00', bill_rate: '425.00' }],
          }),
        })
      }
      if (url === '/api/vacancies/' && options?.method === 'POST') {
        return vacancyResponse.promise
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: /Add vacancy/ }))
    await user.type(screen.getByLabelText('Reference'), 'Delayed cover')
    await user.selectOptions(screen.getByLabelText('Facility'), '7')
    await user.selectOptions(screen.getByLabelText('Role'), '9')
    await user.type(screen.getByLabelText('Start 1'), '2026-09-12T06:00')
    await user.clear(screen.getByLabelText('End 1'))
    await user.type(screen.getByLabelText('End 1'), '2026-09-12T18:00')
    await user.click(screen.getByRole('button', { name: 'Create vacancy' }))
    await user.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(await screen.findByRole('heading', { name: 'Sign in to IMMploy' })).toBeInTheDocument()

    await act(async () => vacancyResponse.resolve({
      ok: true,
      json: async () => ({
        id: 88,
        reference: 'Delayed cover',
        shifts: [{ ...openShift, id: 88, client_name: 'Sensitive Delayed Facility' }],
      }),
    }))

    expect(screen.queryByText('Sensitive Delayed Facility')).not.toBeInTheDocument()
    expect(screen.queryByText(/Vacancy created/)).not.toBeInTheDocument()
  })

  it('loads only facility-linked roles and populates their rates', async () => {
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      if (url === '/api/shifts/') {
        return Promise.resolve({ ok: true, json: async () => [openShift] })
      }
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            authenticated: true,
            permissions: {
              manage_bookings: true,
              view_candidate_pay_rates: true,
              override_approved_rates: true,
            },
          }),
        })
      }
      if (url === '/api/vacancies/creation-options/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            sites: [{ id: 7, name: 'Main facility', client_name: 'Linked Hospital' }],
            professions: [{ id: 99, name: 'Unlinked Nurse' }],
          }),
        })
      }
      if (url === '/api/vacancies/site-role-options/?site=7') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            professions: [{
              id: 9,
              name: 'Linked Nurse',
              pay_rate: '245.50',
              bill_rate: '455.75',
            }],
          }),
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    }))
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: /Add vacancy/ }))
    await user.selectOptions(screen.getByLabelText('Facility'), '7')

    expect(await screen.findByRole('option', { name: 'Linked Nurse' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Unlinked Nurse' })).not.toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('Role'), '9')
    expect(screen.getByLabelText('Pay rate')).toHaveValue(245.5)
    expect(screen.queryByLabelText('Bill rate')).not.toBeInTheDocument()
  })

  it('ignores a stale rate response after the facility changes', async () => {
    const firstRate = deferred<{ ok: boolean, json: () => Promise<object> }>()
    const secondRate = deferred<{ ok: boolean, json: () => Promise<object> }>()
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      if (url === '/api/shifts/') {
        return Promise.resolve({ ok: true, json: async () => [openShift] })
      }
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            authenticated: true,
            permissions: {
              manage_bookings: true,
              view_candidate_pay_rates: true,
              override_approved_rates: true,
            },
          }),
        })
      }
      if (url === '/api/vacancies/creation-options/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            sites: [
              { id: 7, name: 'Ward A', client_name: 'First Hospital' },
              { id: 8, name: 'Ward B', client_name: 'Second Hospital' },
            ],
            professions: [{ id: 9, name: 'Registered Nurse' }],
          }),
        })
      }
      if (url === '/api/vacancies/site-role-options/?site=7') return firstRate.promise
      if (url === '/api/vacancies/site-role-options/?site=8') return secondRate.promise
      throw new Error(`Unexpected request: ${url}`)
    }))
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: /Add vacancy/ }))
    await user.selectOptions(screen.getByLabelText('Facility'), '7')
    await user.selectOptions(screen.getByLabelText('Facility'), '8')

    await act(async () => {
      secondRate.resolve({
        ok: true,
        json: async () => ({
          professions: [{
            id: 9,
            name: 'Registered Nurse',
            pay_rate: '300.00',
            bill_rate: '500.00',
          }],
        }),
      })
    })
    await user.selectOptions(screen.getByLabelText('Role'), '9')
    expect(screen.getByLabelText('Pay rate')).toHaveValue(300)

    await act(async () => {
      firstRate.resolve({
        ok: true,
        json: async () => ({
          professions: [{
            id: 10,
            name: 'Stale Nurse',
            pay_rate: '200.00',
            bill_rate: '400.00',
          }],
        }),
      })
    })
    expect(screen.queryByRole('option', { name: 'Stale Nurse' })).not.toBeInTheDocument()
    expect(screen.getByLabelText('Pay rate')).toHaveValue(300)
  })

  it('submits password sign-in with Enter without leaving the booking board', async () => {
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
      if (url === '/api/shifts/') {
        return Promise.resolve({ ok: true, json: async () => [openShift] })
      }
      if (url === '/api/session/' && !options?.method) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ authenticated: false, user: null }),
        })
      }
      if (url === '/api/session/' && options?.method === 'POST') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            authenticated: true,
            user: { username: 'demo.staff', display_name: 'Demo' },
            permissions: { manage_bookings: true },
          }),
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    expect(await screen.findByRole('heading', { name: 'Sign in to IMMploy' })).toBeInTheDocument()
    expect(screen.queryByText('No shifts yet. Create the first shift to get started.'))
      .not.toBeInTheDocument()
    expect(screen.getByLabelText('Username')).toHaveFocus()
    await user.type(screen.getByLabelText('Username'), 'demo.staff')
    await user.type(screen.getByLabelText('Password'), 'test-password{Enter}')

    expect(await screen.findByText('Rosebank Day Hospital')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/session/',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          username: 'demo.staff',
          password: 'test-password',
        }),
      }),
    )
  })

  it('submits password and Microsoft Authenticator stages with Enter', async () => {
    let loginRequests = 0
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
      if (url === '/api/shifts/') {
        return Promise.resolve({ ok: true, json: async () => [openShift] })
      }
      if (url === '/api/session/' && !options?.method) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ authenticated: false, user: null }),
        })
      }
      if (url === '/api/session/' && options?.method === 'POST') {
        loginRequests += 1
        if (loginRequests === 1) {
          return Promise.resolve({
            ok: true,
            status: 202,
            json: async () => ({ mfa_required: true }),
          })
        }
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            authenticated: true,
            mfa_enabled: true,
            permissions: { manage_bookings: true },
          }),
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    await user.type(await screen.findByLabelText('Username'), 'demo.staff')
    await user.type(screen.getByLabelText('Password'), 'test-password{Enter}')

    expect(await screen.findByRole('heading', { name: 'Verify with Microsoft Authenticator' }))
      .toBeInTheDocument()
    expect(screen.getByText(
      'On the trusted IMMploy LAN, this browser will remember MFA for 30 days.',
    )).toBeInTheDocument()
    expect(screen.getByLabelText('Authenticator code')).toHaveFocus()
    await user.type(screen.getByLabelText('Authenticator code'), '123456{Enter}')

    expect(await screen.findByText('Rosebank Day Hospital')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/session/',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ mfa_code: '123456' }),
      }),
    )
  })

  it('enrolls Microsoft Authenticator from sign-in security', async () => {
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
      if (url === '/api/shifts/') {
        return Promise.resolve({ ok: true, json: async () => [openShift] })
      }
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            authenticated: true,
            mfa_enabled: false,
            permissions: { manage_bookings: true },
          }),
        })
      }
      if (url === '/api/mfa/' && !options?.method) {
        return Promise.resolve({ ok: true, json: async () => ({ enabled: false }) })
      }
      if (url === '/api/mfa/' && options?.method === 'POST') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            enabled: false,
            qr_code_data_url: 'data:image/svg+xml;base64,PHN2Zy8+',
          }),
        })
      }
      if (url === '/api/mfa/' && options?.method === 'PUT') {
        return Promise.resolve({ ok: true, json: async () => ({ enabled: true }) })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: 'Sign-in security' }))
    expect(await screen.findByRole('heading', { name: 'Microsoft Authenticator' }))
      .toBeInTheDocument()
    await user.type(screen.getByLabelText('Current password'), 'test-password')
    await user.click(screen.getByRole('button', { name: 'Set up Microsoft Authenticator' }))
    expect(await screen.findByAltText('Microsoft Authenticator setup QR code'))
      .toBeInTheDocument()
    await user.type(screen.getByLabelText('Authenticator code'), '654321')
    await user.click(screen.getByRole('button', { name: 'Enable MFA' }))

    expect(await screen.findByText('Multi-factor authentication is enabled.'))
      .toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/mfa/',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ password: 'test-password' }),
      }),
    )
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/mfa/',
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({ code: '654321' }),
      }),
    )
  })

  it('ignores a delayed MFA setup response after sign-out', async () => {
    let resolveMfaSetup!: (response: {
      ok: boolean
      json: () => Promise<{ enabled: boolean; qr_code_data_url: string }>
    }) => void
    const delayedMfaSetup = new Promise<{
      ok: boolean
      json: () => Promise<{ enabled: boolean; qr_code_data_url: string }>
    }>((resolve) => { resolveMfaSetup = resolve })
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
      if (url === '/api/shifts/') {
        return Promise.resolve({ ok: true, json: async () => [openShift] })
      }
      if (url === '/api/session/' && options?.method === 'DELETE') {
        return Promise.resolve({ ok: true, json: async () => ({ authenticated: false }) })
      }
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            authenticated: true,
            mfa_enabled: false,
            permissions: { manage_bookings: true },
          }),
        })
      }
      if (url === '/api/mfa/' && !options?.method) {
        return Promise.resolve({ ok: true, json: async () => ({ enabled: false }) })
      }
      if (url === '/api/mfa/' && options?.method === 'POST') return delayedMfaSetup
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: 'Sign-in security' }))
    await user.type(await screen.findByLabelText('Current password'), 'test-password')
    await user.click(screen.getByRole('button', { name: 'Set up Microsoft Authenticator' }))
    await user.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(await screen.findByRole('heading', { name: 'Sign in to IMMploy' })).toBeInTheDocument()

    await act(async () => resolveMfaSetup({
      ok: true,
      json: async () => ({
        enabled: false,
        qr_code_data_url: 'data:image/svg+xml;base64,PHN2Zy8+',
      }),
    }))
    expect(screen.queryByAltText('Microsoft Authenticator setup QR code')).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Sign in to IMMploy' })).toBeInTheDocument()

    await user.type(screen.getByLabelText('Username'), 'next.user')
    await user.type(screen.getByLabelText('Password'), 'next-password')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    await user.click(await screen.findByRole('button', { name: 'Sign-in security' }))
    expect(await screen.findByRole('heading', { name: 'Microsoft Authenticator' })).toBeInTheDocument()
    expect(screen.queryByAltText('Microsoft Authenticator setup QR code')).not.toBeInTheDocument()
  })

  it('returns to sign-in after disabling MFA revokes the current session', async () => {
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
      if (url === '/api/shifts/') {
        return Promise.resolve({ ok: true, json: async () => [openShift] })
      }
      if (url === '/api/session/' && !options?.method) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            authenticated: true,
            mfa_enabled: true,
            permissions: { manage_bookings: true },
          }),
        })
      }
      if (url === '/api/mfa/' && !options?.method) {
        return Promise.resolve({ ok: true, json: async () => ({ enabled: true }) })
      }
      if (url === '/api/mfa/' && options?.method === 'DELETE') {
        return Promise.resolve({ ok: true, json: async () => ({ enabled: false }) })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: 'Sign-in security' }))
    await user.type(await screen.findByLabelText('Current authenticator code'), '654321')
    await user.click(screen.getByRole('button', { name: 'Disable MFA' }))

    expect(await screen.findByRole('heading', { name: 'Sign in to IMMploy' })).toBeInTheDocument()
    expect(screen.queryByText('Rosebank Day Hospital')).not.toBeInTheDocument()
  })

  it('waits for CSRF preparation before enabling sign-in', async () => {
    let resolveSession!: (value: { ok: boolean, json: () => Promise<object> }) => void
    const sessionRequest = new Promise<{ ok: boolean, json: () => Promise<object> }>((resolve) => {
      resolveSession = resolve
    })
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      if (url === '/api/session/') return sessionRequest
      throw new Error(`Unexpected request: ${url}`)
    }))

    render(<App />)
    const signIn = await screen.findByRole('button', { name: 'Sign in' })
    expect(signIn).toBeDisabled()

    await act(async () => resolveSession({
      ok: true,
      json: async () => ({ authenticated: false, user: null }),
    }))
    await waitFor(() => expect(signIn).toBeEnabled())
  })

  it('uses a safe fallback when a failed login returns null JSON', async () => {
    vi.stubGlobal('fetch', vi.fn((url: string, options?: RequestInit) => {
      if (url === '/api/session/' && !options?.method) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ authenticated: false, user: null }),
        })
      }
      if (url === '/api/session/' && options?.method === 'POST') {
        return Promise.resolve({ ok: false, json: async () => null })
      }
      throw new Error(`Unexpected request: ${url}`)
    }))

    const user = userEvent.setup()
    render(<App />)
    await user.type(await screen.findByLabelText('Username'), 'demo.staff')
    await user.type(screen.getByLabelText('Password'), 'wrong')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not sign in')
  })

  it('shows shift-load errors after authentication instead of returning to login', async () => {
    let shiftAttempts = 0
    vi.stubGlobal('fetch', vi.fn((url: string, options?: RequestInit) => {
      if (url === '/api/shifts/') {
        shiftAttempts += 1
        return Promise.resolve(shiftAttempts === 1
          ? { ok: false, status: 500 }
          : { ok: true, json: async () => [openShift] })
      }
      if (url === '/api/session/' && !options?.method) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ authenticated: false, user: null }),
        })
      }
      if (url === '/api/session/' && options?.method === 'POST') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            authenticated: true,
            permissions: { manage_bookings: true },
          }),
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    }))

    const user = userEvent.setup()
    render(<App />)
    await user.type(await screen.findByLabelText('Username'), 'demo.staff')
    await user.type(screen.getByLabelText('Password'), 'test-password')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByText('Could not load shifts')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Sign in to IMMploy' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Retry shifts' }))
    expect(await screen.findByText('Rosebank Day Hospital')).toBeInTheDocument()
    expect(shiftAttempts).toBe(2)
  })

  it('finds an eligible candidate and confirms the booking', async () => {
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
      if (url === '/api/shifts/') {
        return Promise.resolve({ ok: true, json: async () => [openShift] })
      }
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            authenticated: true,
            permissions: { manage_bookings: true },
          }),
        })
      }
      if (url === '/api/shifts/1/candidates/') {
        return Promise.resolve({
          ok: true,
          json: async () => [
            {
              id: 12,
              full_name: 'Lerato Maseko',
              compliance_status: 'cleared',
              role_name: 'Registered Nurse',
              home_area: 'Parktown',
              home_region: 'Gauteng',
              worked_at_facility: true,
              facility_shift_count: 8,
              last_worked_on: '2026-06-14',
              proximity_label: 'Same region as facility',
              eligibility_reasons: [
                'Compliance cleared',
                'Registered Nurse role matched',
                '8 completed shifts at this facility',
                'Same region as facility',
              ],
            },
            {
              id: 13,
              full_name: 'Another Eligible',
              compliance_status: 'cleared',
              role_name: 'Registered Nurse',
              eligibility_reasons: ['Compliance cleared'],
            },
          ],
        })
      }
      if (url === '/api/bookings/' && options?.method === 'POST') {
        return Promise.resolve({
          ok: true,
          json: async () => ({ id: 9, shift: 1, candidate: 12, status: 'confirmed' }),
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: 'Add candidate' }))
    expect(screen.getByRole('dialog', { name: 'Eligible candidates' })).toHaveAttribute(
      'aria-modal',
      'true',
    )
    expect(await screen.findByText('Lerato Maseko')).toBeInTheDocument()
    expect(screen.getByText('Another Eligible')).toBeInTheDocument()
    await user.type(screen.getByLabelText('Search eligible candidates'), 'Lerato')
    expect(screen.queryByText('Another Eligible')).not.toBeInTheDocument()
    expect(screen.getByText('Previously worked here')).toBeInTheDocument()
    expect(screen.getByText('8 completed shifts at this facility')).toBeInTheDocument()
    expect(screen.getByText('Same region as facility')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Add Lerato Maseko to booking' }))

    expect(await screen.findByText('Booking confirmed')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/bookings/',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ shift: 1, candidate: 12, status: 'confirmed' }),
      }),
    )
  })

  it('can search the full directory while showing authoritative booking rejection reasons', async () => {
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({ authenticated: true, permissions: { manage_bookings: true } }),
        })
      }
      if (url === '/api/shifts/') {
        return Promise.resolve({ ok: true, json: async () => [openShift] })
      }
      if (url === '/api/shifts/1/candidates/') {
        return Promise.resolve({ ok: true, json: async () => [] })
      }
      if (url === '/api/candidates/?search=&profession=9') {
        return Promise.resolve({
          ok: true,
          json: async () => [{
            id: 91,
            full_name: 'Manual Candidate',
            compliance_status: 'pending',
            home_area: 'Soweto',
            home_region: 'Gauteng',
            profession_names: ['Registered Nurse'],
          }],
        })
      }
      if (url === '/api/bookings/' && options?.method === 'POST') {
        return Promise.resolve({
          ok: false,
          status: 400,
          json: async () => ({ non_field_errors: ['Candidate compliance must be cleared.'] }),
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: 'Add candidate' }))
    expect(await screen.findByText('No compliance-cleared candidates match this shift.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Search full candidate directory' }))

    expect(await screen.findByText('Manual Candidate')).toBeInTheDocument()
    expect(screen.getByText('Not prevalidated')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Add Manual Candidate to booking' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Candidate compliance must be cleared.',
    )
  })

  it('does not expose booking actions when legacy access rules deny them', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            authenticated: true,
            access_rules: { link_conf: false },
            permissions: { manage_bookings: false },
          }),
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    expect(await screen.findByRole('button', { name: /Add vacancy/ })).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Add candidate' })).not.toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalledWith('/api/shifts/', expect.anything())
  })

  it('disables confirmation while the booking request is pending', async () => {
    let resolveBooking!: (value: { ok: boolean; json: () => Promise<object> }) => void
    const pendingBooking = new Promise<{ ok: boolean; json: () => Promise<object> }>((resolve) => {
      resolveBooking = resolve
    })
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
      if (url === '/api/shifts/') {
        return Promise.resolve({ ok: true, json: async () => [openShift] })
      }
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            authenticated: true,
            permissions: { manage_bookings: true },
          }),
        })
      }
      if (url === '/api/shifts/1/candidates/') {
        return Promise.resolve({
          ok: true,
          json: async () => [{ id: 12, full_name: 'Lerato Maseko', compliance_status: 'cleared' }],
        })
      }
      if (url === '/api/bookings/' && options?.method === 'POST') return pendingBooking
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: 'Add candidate' }))
    const confirm = await screen.findByRole('button', { name: 'Add Lerato Maseko to booking' })
    await user.click(confirm)

    expect(confirm).toBeDisabled()
    expect(confirm).toHaveTextContent('Adding…')
    expect(screen.getByRole('button', { name: 'Close candidate finder' })).toBeDisabled()
    await user.click(confirm)
    expect(fetchMock.mock.calls.filter(([url]) => url === '/api/bookings/')).toHaveLength(1)

    await act(async () => resolveBooking({ ok: true, json: async () => ({}) }))
  })

  it('ignores a successful booking response after sign-out clears the session', async () => {
    let resolveBooking!: (value: { ok: boolean; json: () => Promise<object> }) => void
    const pendingBooking = new Promise<{ ok: boolean; json: () => Promise<object> }>((resolve) => {
      resolveBooking = resolve
    })
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
      if (url === '/api/session/' && options?.method === 'DELETE') {
        return Promise.resolve({ ok: true, json: async () => ({}) })
      }
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({ authenticated: true, permissions: { manage_bookings: true } }),
        })
      }
      if (url === '/api/shifts/') {
        return Promise.resolve({ ok: true, json: async () => [openShift] })
      }
      if (url === '/api/shifts/1/candidates/') {
        return Promise.resolve({
          ok: true,
          json: async () => [{ id: 12, full_name: 'Lerato Maseko', compliance_status: 'cleared' }],
        })
      }
      if (url === '/api/bookings/' && options?.method === 'POST') return pendingBooking
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: 'Add candidate' }))
    await user.click(await screen.findByRole('button', { name: 'Add Lerato Maseko to booking' }))
    await user.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(await screen.findByRole('heading', { name: 'Sign in to IMMploy' })).toBeInTheDocument()

    await act(async () => resolveBooking({ ok: true, json: async () => ({}) }))

    expect(screen.queryByText('Booking confirmed')).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Sign in to IMMploy' })).toBeInTheDocument()
  })

  it('ignores a successful bulk-booking response after sign-out clears the session', async () => {
    let resolveBulk!: (value: { ok: boolean; json: () => Promise<object[]> }) => void
    const pendingBulk = new Promise<{ ok: boolean; json: () => Promise<object[]> }>((resolve) => {
      resolveBulk = resolve
    })
    const candidate = {
      id: 51,
      full_name: 'Nomsa Directory',
      compliance_status: 'cleared',
      home_area: 'Rosebank',
      home_region: 'Gauteng',
      profession_names: ['Registered Nurse'],
    }
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
      if (url === '/api/session/' && options?.method === 'DELETE') {
        return Promise.resolve({ ok: true, json: async () => ({}) })
      }
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({ authenticated: true, permissions: { manage_bookings: true } }),
        })
      }
      if (url === '/api/shifts/') {
        return Promise.resolve({ ok: true, json: async () => [openShift] })
      }
      if (url === '/api/candidates/') {
        return Promise.resolve({ ok: true, json: async () => [candidate] })
      }
      if (url === '/api/candidates/51/compatible-shifts/') {
        return Promise.resolve({ ok: true, json: async () => [openShift] })
      }
      if (url === '/api/bookings/bulk/' && options?.method === 'POST') return pendingBulk
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: 'Candidates' }))
    await user.click(await screen.findByRole('button', { name: 'Book shifts for Nomsa Directory' }))
    const dialog = await screen.findByRole('dialog', { name: 'Book multiple shifts for Nomsa Directory' })
    await user.click(within(dialog).getByRole('checkbox'))
    await user.click(within(dialog).getByRole('button', { name: 'Book 1 shift' }))
    await user.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(await screen.findByRole('heading', { name: 'Sign in to IMMploy' })).toBeInTheDocument()

    await act(async () => resolveBulk({
      ok: true,
      json: async () => [{ id: 401, shift: 1, candidate: 51, status: 'confirmed' }],
    }))

    expect(screen.queryByText('1 bookings confirmed')).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Sign in to IMMploy' })).toBeInTheDocument()
  })

  it('ignores candidates returned for a previously selected shift', async () => {
    let resolveFirst!: (value: { ok: boolean; json: () => Promise<object[]> }) => void
    const firstCandidates = new Promise<{ ok: boolean; json: () => Promise<object[]> }>((resolve) => {
      resolveFirst = resolve
    })
    const fetchMock = vi.fn((url: string) => {
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({ authenticated: true, permissions: { manage_bookings: true } }),
        })
      }
      if (url === '/api/shifts/') {
        return Promise.resolve({ ok: true, json: async () => [openShift, secondOpenShift] })
      }
      if (url === '/api/shifts/1/candidates/') return firstCandidates
      if (url === '/api/shifts/2/candidates/') {
        return Promise.resolve({
          ok: true,
          json: async () => [{ id: 22, full_name: 'Current Candidate', compliance_status: 'cleared' }],
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    const findButtons = await screen.findAllByRole('button', { name: 'Add candidate' })
    await user.click(findButtons[0])
    await user.click(screen.getByRole('button', { name: 'Close candidate finder' }))
    await user.click(findButtons[1])
    expect(await screen.findByText('Current Candidate')).toBeInTheDocument()

    await act(async () => resolveFirst({
      ok: true,
      json: async () => [{ id: 11, full_name: 'Stale Candidate', compliance_status: 'cleared' }],
    }))

    expect(screen.queryByText('Stale Candidate')).not.toBeInTheDocument()
    expect(screen.getByText('Current Candidate')).toBeInTheDocument()
  })

  it('shows candidate-load failures instead of a misleading empty result', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url === '/api/session/') {
        return {
          ok: true,
          json: async () => ({ authenticated: true, permissions: { manage_bookings: true } }),
        }
      }
      if (url === '/api/shifts/') {
        return { ok: true, json: async () => [openShift] }
      }
      throw new Error('candidate request failed')
    }))

    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'Add candidate' }))

    expect(await screen.findByText('Could not load eligible candidates.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry eligible candidates' })).toBeInTheDocument()
    expect(screen.queryByText('No compliance-cleared candidates for this shift.'))
      .not.toBeInTheDocument()
  })

  it('signs out with CSRF and clears operational state', async () => {
    document.cookie = 'csrftoken=logout-token'
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
      if (url === '/api/shifts/') {
        return Promise.resolve({ ok: true, json: async () => [openShift] })
      }
      if (url === '/api/session/' && options?.method === 'DELETE') {
        return Promise.resolve({ ok: true, json: async () => ({ authenticated: false }) })
      }
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({ authenticated: true, permissions: { manage_bookings: true } }),
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    expect(await screen.findByText('Rosebank Day Hospital')).toBeInTheDocument()
    await user.click(await screen.findByRole('button', { name: 'Sign out' }))

    expect(await screen.findByRole('heading', { name: 'Sign in to IMMploy' })).toBeInTheDocument()
    expect(screen.queryByText('Rosebank Day Hospital')).not.toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith('/api/session/', expect.objectContaining({
      method: 'DELETE',
      credentials: 'same-origin',
      headers: { 'X-CSRFToken': 'logout-token' },
    }))
  })

  it('keeps the authenticated UI and reconciles the session when logout is rejected', async () => {
    document.cookie = 'csrftoken=stale-logout-token'
    let sessionReads = 0
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
      if (url === '/api/session/' && options?.method === 'DELETE') {
        return Promise.resolve({ ok: false, status: 403 })
      }
      if (url === '/api/session/') {
        sessionReads += 1
        return Promise.resolve({
          ok: true,
          json: async () => ({ authenticated: true, permissions: { manage_bookings: true } }),
        })
      }
      if (url === '/api/shifts/') {
        return Promise.resolve({ ok: true, json: async () => [openShift] })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    expect(await screen.findByText('Rosebank Day Hospital')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Sign out' }))

    expect(await screen.findByText('Could not sign out')).toBeInTheDocument()
    expect(screen.getByText('Rosebank Day Hospital')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Sign in to IMMploy' })).not.toBeInTheDocument()
    expect(sessionReads).toBeGreaterThanOrEqual(2)
    const deleteIndex = fetchMock.mock.calls.findIndex(([, options]) => options?.method === 'DELETE')
    expect(fetchMock.mock.calls.slice(deleteIndex + 1).some(
      ([url, options]) => url === '/api/session/' && !options?.method,
    )).toBe(true)
  })

  it('ignores a delayed logout response after a newer session signs in', async () => {
    let resolveLogout!: (response: { ok: boolean; status: number }) => void
    const delayedLogout = new Promise<{ ok: boolean; status: number }>((resolve) => {
      resolveLogout = resolve
    })
    let authorizationDenied = false
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
      if (url === '/api/session/' && options?.method === 'DELETE') return delayedLogout
      if (url === '/api/session/' && options?.method === 'POST') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ authenticated: true, permissions: { manage_bookings: true } }),
        })
      }
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            authenticated: !authorizationDenied,
            permissions: { manage_bookings: true },
          }),
        })
      }
      if (url === '/api/shifts/') {
        return Promise.resolve({ ok: true, json: async () => [openShift] })
      }
      if (url === '/api/candidates/') {
        authorizationDenied = true
        return Promise.resolve({ ok: false, status: 403 })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: 'Sign out' }))
    await user.click(screen.getByRole('button', { name: 'Candidates' }))
    await user.type(await screen.findByLabelText('Username'), 'new.staff')
    await user.type(screen.getByLabelText('Password'), 'test-password')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Rosebank Day Hospital')).toBeInTheDocument()

    await act(async () => resolveLogout({ ok: true, status: 204 }))

    expect(screen.getByRole('button', { name: 'Sign out' })).toBeEnabled()
    expect(screen.queryByRole('heading', { name: 'Sign in to IMMploy' })).not.toBeInTheDocument()
    expect(screen.getByText('Rosebank Day Hospital')).toBeInTheDocument()
  })

  it('preserves a valid authenticated session after an ordinary permission denial', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === '/api/shifts/') {
        return Promise.resolve({ ok: true, json: async () => [openShift] })
      }
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({ authenticated: true, permissions: { manage_bookings: true } }),
        })
      }
      if (url === '/api/candidates/') return Promise.resolve({ ok: false, status: 403 })
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    expect(await screen.findByText('Rosebank Day Hospital')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Candidates' }))

    expect(await screen.findByText('Could not load candidates')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Sign in to IMMploy' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Booking board' }))
    expect(screen.getByText('Rosebank Day Hospital')).toBeInTheDocument()
    const denialIndex = fetchMock.mock.calls.findIndex(([url]) => url === '/api/candidates/')
    expect(fetchMock.mock.calls.slice(denialIndex + 1).some(([url]) => url === '/api/session/')).toBe(true)
  })

  it('ignores a delayed successful response after authorization loss', async () => {
    let resolveShiftJson!: (shifts: typeof openShift[]) => void
    const delayedShiftJson = new Promise<typeof openShift[]>((resolve) => {
      resolveShiftJson = resolve
    })
    let authorizationDenied = false
    const fetchMock = vi.fn((url: string) => {
      if (url === '/api/shifts/') {
        return Promise.resolve({ ok: true, json: () => delayedShiftJson })
      }
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            authenticated: !authorizationDenied,
            permissions: { manage_bookings: true, manage_candidates: true },
          }),
        })
      }
      if (url === '/api/candidates/') {
        authorizationDenied = true
        return Promise.resolve({ ok: false, status: 403 })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    await screen.findByRole('button', { name: 'Sign out' })
    await user.click(screen.getByRole('button', { name: 'Candidates' }))
    expect(await screen.findByRole('heading', { name: 'Sign in to IMMploy' })).toBeInTheDocument()

    resolveShiftJson([openShift])

    await waitFor(() => {
      expect(screen.queryByText('Rosebank Day Hospital')).not.toBeInTheDocument()
      expect(screen.getByRole('heading', { name: 'Sign in to IMMploy' })).toBeInTheDocument()
    })
  })

  it('ignores a stale authorization failure after a new session signs in', async () => {
    let resolveOldShift!: (response: { ok: boolean; status: number }) => void
    const oldShiftResponse = new Promise<{ ok: boolean; status: number }>((resolve) => {
      resolveOldShift = resolve
    })
    let shiftRequests = 0
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
      if (url === '/api/session/' && options?.method === 'DELETE') {
        return Promise.resolve({ ok: true })
      }
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            authenticated: true,
            permissions: { manage_bookings: true },
          }),
        })
      }
      if (url === '/api/shifts/') {
        shiftRequests += 1
        if (shiftRequests === 1) return oldShiftResponse
        return Promise.resolve({ ok: true, json: async () => [openShift] })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: 'Sign out' }))
    await user.type(await screen.findByLabelText('Username'), 'second.staff')
    await user.type(screen.getByLabelText('Password'), 'test-password')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Rosebank Day Hospital')).toBeInTheDocument()

    await act(async () => resolveOldShift({ ok: false, status: 403 }))

    expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Sign in to IMMploy' })).not.toBeInTheDocument()
    expect(screen.getByText('Rosebank Day Hospital')).toBeInTheDocument()
  })

  it('does not grant candidate editing when a booking-only session omits that permission', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            authenticated: true,
            permissions: { manage_bookings: true },
          }),
        })
      }
      if (url === '/api/shifts/') {
        return Promise.resolve({ ok: true, json: async () => [openShift] })
      }
      if (url === '/api/candidates/') {
        return Promise.resolve({ ok: true, json: async () => [] })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: 'Candidates' }))
    expect(await screen.findByRole('heading', { name: 'Candidates' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add candidate' })).not.toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalledWith('/api/candidates/creation-options/')
  })

  it('allows a candidate editor without scheduling access to add candidates', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            authenticated: true,
            permissions: { manage_bookings: false, manage_candidates: true },
          }),
        })
      }
      if (url === '/api/candidates/') {
        return Promise.resolve({ ok: true, json: async () => [] })
      }
      if (url === '/api/candidates/creation-options/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({ professions: [{ id: 1, name: 'Registered Nurse' }] }),
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    expect(await screen.findByRole('heading', { name: 'Candidates' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Booking board' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Clients' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reports' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument()
    const addCandidate = screen.getByRole('button', { name: 'Add candidate' })
    expect(addCandidate).toBeEnabled()
    await user.click(addCandidate)

    expect(await screen.findByLabelText('Candidate role')).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalledWith('/api/vacancies/creation-options/', expect.anything())
    expect(fetchMock).not.toHaveBeenCalledWith('/api/shifts/', expect.anything())
  })

  it.each([
    'Authenticator challenge expired.',
    'Start sign-in again.',
  ])('returns an invalid MFA challenge to password sign-in: %s', async (challengeError) => {
    let loginRequests = 0
    vi.stubGlobal('fetch', vi.fn((url: string, options?: RequestInit) => {
      if (url === '/api/session/' && !options?.method) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ authenticated: false, user: null }),
        })
      }
      if (url === '/api/session/' && options?.method === 'POST') {
        loginRequests += 1
        if (loginRequests === 1) {
          return Promise.resolve({
            ok: true,
            status: 202,
            json: async () => ({ mfa_required: true }),
          })
        }
        return Promise.resolve({
          ok: false,
          status: 400,
          json: async () => ({ error: challengeError }),
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    }))
    const user = userEvent.setup()
    render(<App />)

    await user.type(await screen.findByLabelText('Username'), 'demo.staff')
    await user.type(screen.getByLabelText('Password'), 'test-password')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    await user.type(await screen.findByLabelText('Authenticator code'), '123456')
    await user.click(screen.getByRole('button', { name: 'Verify code' }))

    expect(await screen.findByRole('heading', { name: 'Sign in to IMMploy' })).toBeInTheDocument()
    expect(screen.getByLabelText('Username')).toHaveValue('demo.staff')
    expect(screen.getByLabelText('Password')).toHaveValue('')
    expect(screen.getByRole('alert')).toHaveTextContent(challengeError)
  })

  it('allows backing out of an MFA challenge to restart password sign-in', async () => {
    let loginRequests = 0
    vi.stubGlobal('fetch', vi.fn((url: string, options?: RequestInit) => {
      if (url === '/api/session/' && !options?.method) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ authenticated: false, user: null }),
        })
      }
      if (url === '/api/session/' && options?.method === 'POST') {
        loginRequests += 1
        return Promise.resolve({
          ok: true,
          status: 202,
          json: async () => ({ mfa_required: true }),
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    }))
    const user = userEvent.setup()
    render(<App />)

    await user.type(await screen.findByLabelText('Username'), 'demo.staff')
    await user.type(screen.getByLabelText('Password'), 'test-password')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    await user.click(await screen.findByRole('button', { name: 'Back to password sign-in' }))

    expect(screen.getByRole('heading', { name: 'Sign in to IMMploy' })).toBeInTheDocument()
    expect(screen.getByLabelText('Username')).toHaveValue('demo.staff')
    expect(screen.getByLabelText('Password')).toHaveValue('')
    expect(screen.getByLabelText('Password')).toHaveFocus()
  })

  it.each([
    'MFA enrollment expired. Start again.',
    'Invalid authenticator enrollment. Start again.',
  ])('discards an unusable MFA enrollment and requires password-gated setup again: %s', async (enrollmentError) => {
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
      if (url === '/api/shifts/') {
        return Promise.resolve({ ok: true, json: async () => [openShift] })
      }
      if (url === '/api/session/') {
        return Promise.resolve({
          ok: true,
          json: async () => ({ authenticated: true, permissions: { manage_bookings: true } }),
        })
      }
      if (url === '/api/mfa/' && !options?.method) {
        return Promise.resolve({ ok: true, json: async () => ({ enabled: false }) })
      }
      if (url === '/api/mfa/' && options?.method === 'POST') {
        return Promise.resolve({
          ok: true,
          json: async () => ({ qr_code_data_url: 'data:image/svg+xml;base64,PHN2Zy8+' }),
        })
      }
      if (url === '/api/mfa/' && options?.method === 'PUT') {
        return Promise.resolve({
          ok: false,
          status: 400,
          json: async () => ({ error: enrollmentError }),
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: 'Sign-in security' }))
    await user.type(await screen.findByLabelText('Current password'), 'test-password')
    await user.click(screen.getByRole('button', { name: 'Set up Microsoft Authenticator' }))
    await user.type(await screen.findByLabelText('Authenticator code'), '654321')
    await user.click(screen.getByRole('button', { name: 'Enable MFA' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(enrollmentError)
    expect(screen.queryByAltText('Microsoft Authenticator setup QR code')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Current password')).toHaveValue('')
    expect(screen.getByRole('button', { name: 'Set up Microsoft Authenticator' })).toBeInTheDocument()
  })
})