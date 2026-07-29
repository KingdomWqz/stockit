import axios from 'axios';

const api = axios.create({
  baseURL: '/svc/api',
  timeout: 10000,
});

export { api };
