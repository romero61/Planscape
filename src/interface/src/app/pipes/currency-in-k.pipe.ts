import { Pipe, PipeTransform } from '@angular/core';
import { CurrencyPipe } from '@angular/common';

/**
 * Todo, should this return 1M or 1,000K ?
 * Update tests and name accordingly
 */
@Pipe({
  name: 'currencyInK',
})
export class CurrencyInKPipe implements PipeTransform {
  readonly denominator = 'K';
  constructor(public currencyPipe: CurrencyPipe) {}

  transform(value: number): string | null {
    if (value === 0) {
      return '$0';
    }
    return (
      this.currencyPipe.transform(value / 1000, 'USD', 'symbol', '1.0-2') +
      this.denominator
    );
  }
}
