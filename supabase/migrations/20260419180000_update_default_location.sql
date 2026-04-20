-- STAR-ASN Default Location Update
-- Updates the system-wide default location and coordinates.

UPDATE public.settings
SET value = 'Kementerian Imigrasi dan Pemasyarakatan Republik Indonesia'
WHERE key = 'default_location';

UPDATE public.settings
SET value = '-6.2210973'
WHERE key = 'default_latitude';

UPDATE public.settings
SET value = '106.8314724'
WHERE key = 'default_longitude';
