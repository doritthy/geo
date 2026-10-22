'use client';

import { useEffect, useState } from 'react';
import proj4 from 'proj4';
import { twinApi } from './api';
import { tr } from '@/lib/i18n';

export interface ProjectCrs {
  label: string;
  /** lon/lat (WGS84) -> project CRS x/y; null when the CRS is geographic or unknown. */
  forward: ((lon: number, lat: number) => [number, number]) | null;
}

/** Resolves the project's CRS (EPSG / PROJ / WKT) through the API and builds
 * a proj4 converter so the UI can show coordinates "в требуемой системе координат". */
export function useProjectCrs(crs: string | null | undefined): ProjectCrs {
  const [state, setState] = useState<ProjectCrs>({ label: 'WGS 84', forward: null });

  useEffect(() => {
    let cancelled = false;
    if (!crs) {
      setState({ label: 'WGS 84', forward: null });
      return;
    }
    twinApi
      .resolveCrs(crs)
      .then((info) => {
        if (cancelled) return;
        if (info.is_geographic) {
          setState({ label: info.code ?? info.name, forward: null });
          return;
        }
        const conv = proj4('EPSG:4326', info.proj4);
        setState({
          label: info.code ?? info.name,
          forward: (lon, lat) => conv.forward([lon, lat]) as [number, number],
        });
      })
      .catch(() => !cancelled && setState({ label: `${crs} (${tr('не распознана')})`, forward: null }));
    return () => {
      cancelled = true;
    };
  }, [crs]);

  return state;
}
