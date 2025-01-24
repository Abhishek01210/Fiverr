import { useEffect, useState } from 'react';

export default function useSSE(url: string) {
  const [data, setData] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const eventSource = new EventSource(url);

    eventSource.onmessage = (event) => {
      setData(event.data);
    };

    eventSource.onerror = () => {
      setError('SSE Connection Error');
      eventSource.close();
    };

    return () => eventSource.close();
  }, [url]);

  return { data, error };
}
