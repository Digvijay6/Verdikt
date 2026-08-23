-- Fields needed to publish a job to Google for Jobs.
--
-- Additive. The existing screening_profile.locations is a *filter* — who may
-- be rejected — which is a different thing from where the role is advertised as
-- being. A remote-friendly role can still be posted as based in Berlin, and a
-- filter that lists three acceptable cities has no single location to publish.

alter table job
  add column if not exists location text,
  add column if not exists remote boolean not null default false,
  add column if not exists employment_type text
    check (employment_type in (
      'FULL_TIME','PART_TIME','CONTRACTOR','TEMPORARY',
      'INTERN','VOLUNTEER','PER_DIEM','OTHER'
    )),
  -- Google issues a manual action removing *all* of a site's jobs when stale
  -- undated postings accumulate. Defaults to 60 days out so a job is never
  -- published without an expiry; closing a job pulls it earlier.
  add column if not exists valid_through timestamptz;

comment on column job.location is
  'Display location for the public posting, e.g. "Berlin, Germany". Distinct
   from screening_profile.locations, which gates applicants.';
comment on column job.valid_through is
  'Google removes listings past this date. Absent or stale values risk a manual
   action against every job on the domain.';
