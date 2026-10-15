export const state = { user: null, version: '' };

export const can = (role) => {
  const order = ['viewer', 'editor', 'admin'];
  return state.user && order.indexOf(state.user.role) >= order.indexOf(role);
};
