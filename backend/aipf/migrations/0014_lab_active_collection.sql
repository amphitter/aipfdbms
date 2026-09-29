-- One active collection per ordered test. Rejected samples stay, with the
-- marker cleared, so a later recollection can insert a new active link.
ALTER TABLE lab_sample_items ADD COLUMN active_item INTEGER;

UPDATE lab_sample_items
   SET active_item = 1
 WHERE sample_id IN (SELECT id FROM lab_samples WHERE status <> 'REJECTED');

CREATE UNIQUE INDEX IF NOT EXISTS uq_lab_active_collection
  ON lab_sample_items(order_item_id)
  WHERE active_item = 1;
