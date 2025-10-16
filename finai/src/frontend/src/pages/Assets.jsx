import { Typography, Box } from '@mui/material'

export default function Assets() {
  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Assets
      </Typography>
      <Typography variant="body1" color="text.secondary">
        Manage the stocks, bonds, and other financial assets you want to monitor for liquidity risk.
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
        (Full implementation coming soon - will include asset list, add/edit functionality, and bulk import)
      </Typography>
    </Box>
  )
}
