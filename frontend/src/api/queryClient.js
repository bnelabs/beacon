import { QueryClient } from 'react-query';

export const queryClient = new QueryClient();

export const invalidateQueries = (queries) => {
  queries.forEach(query => {
    queryClient.invalidateQueries(query);
  });
};