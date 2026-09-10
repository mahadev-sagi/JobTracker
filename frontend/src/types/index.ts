export enum ApplicationStatus {
  UNAPPLIED = 'UNAPPLIED',
  APPLIED = 'APPLIED',
  OA_RECEIVED = 'OA_RECEIVED',
  INTERVIEW_SCHEDULED = 'INTERVIEW_SCHEDULED',
  OFFERED = 'OFFERED',
  REJECTED = 'REJECTED'
}

export interface Application {
  id: string;
  company: string;
  role: string;
  status: ApplicationStatus;
  date_posted?: string;
  date_applied?: string;
  notes?: string;
  link?: string;
}

export interface ApplicationStats {
  total: number;
  applied: number;
  interviews: number;
  offers: number;
  rejected: number;
}

export interface Column {
  id: ApplicationStatus;
  title: string;
}

export interface ApiResponse<T> {
  data: T;
  message?: string;
}
