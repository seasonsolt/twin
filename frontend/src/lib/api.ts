import { getPersonaId } from './persona';

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly detail: unknown = null,
    public readonly jobId: string | null = null,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

const errors: Record<number, string> = {
  400: '请求参数有误',
  403: '请求被安全策略拒绝',
  404: '找不到请求的资源',
  409: '操作冲突，请稍后重试',
  413: '请求内容太大',
  429: '请求过于频繁，请稍后重试',
  500: '服务器内部错误',
  503: '服务暂时不可用',
};

export type ApiOptions = Omit<RequestInit, 'body'> & {
  json?: unknown;
  form?: FormData;
  responseType?: 'json' | 'text';
};

export async function api<T>(
  path: string,
  options: ApiOptions = {},
): Promise<T> {
  if (!path.startsWith('/api/') || path.includes('\\')) {
    throw new ApiError(0, '仅允许访问本地 API');
  }
  const { json, form, responseType = 'json', ...init } = options;
  if (json !== undefined && form)
    throw new ApiError(0, '不能同时发送 JSON 和表单');
  const method = (init.method ?? 'GET').toUpperCase();
  const headers = new Headers(init.headers);
  headers.delete('X-Twin');
  if (!headers.has('X-Twin-Persona'))
    headers.set('X-Twin-Persona', getPersonaId());
  if (method !== 'GET') headers.set('X-Twin', '1');
  if (json !== undefined) headers.set('Content-Type', 'application/json');
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      method,
      headers,
      body: form ?? (json !== undefined ? JSON.stringify(json) : undefined),
      credentials: 'same-origin',
      redirect: 'error',
    });
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw error;
    throw new ApiError(0, '无法连接本地服务，请检查服务是否启动');
  }
  const data: unknown =
    response.status === 204
      ? null
      : response.ok && responseType === 'text'
        ? await response.text()
        : await response.json().catch(() => null);
  if (!response.ok) {
    const detail =
      data && typeof data === 'object' && 'detail' in data ? data.detail : null;
    throw new ApiError(
      response.status,
      typeof detail === 'string' && /[\u3400-\u9fff]/u.test(detail)
        ? detail
        : (errors[response.status] ?? '请求失败，请重试'),
      detail,
      data &&
        typeof data === 'object' &&
        'job_id' in data &&
        typeof data.job_id === 'string'
        ? data.job_id
        : null,
    );
  }
  return data as T;
}
